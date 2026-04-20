-- =============================================================================
-- Canonical Sessions — per-tenant schema (governance-hub Postgres)
--
-- Authoritative session objects that represent one continuous user ↔ agent
-- interaction across any surface (OWUI, Mattermost, Teams, Slack, n8n, API).
-- Every surface binds to a canonical session via an adapter; this schema is
-- the single source of truth for participants, transcript, policy context,
-- and audit.
--
-- Lives in the per-tenant governance-hub database. NEVER centralized.
-- Central MSSQL receives aggregated rollups + chain-head attestations only.
--
-- Migration target: 3.3 (post-demo). Idempotent (CREATE IF NOT EXISTS).
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- Enums
-- -----------------------------------------------------------------------------

DO $$ BEGIN
  CREATE TYPE session_owner_type     AS ENUM ('user', 'group', 'agent', 'system');
  CREATE TYPE session_system_reason  AS ENUM (
    'awaiting_callback', 'scheduled_resume', 'retry_backoff',
    'review_queue', 'tenant_migrating'
  );
  CREATE TYPE session_state          AS ENUM (
    'active', 'pending_handoff', 'waiting_user', 'waiting_agent',
    'closed', 'archived', 'forked_closed', 'revoked_by_source',
    'quarantined'
  );
  CREATE TYPE session_classification AS ENUM ('general', 'confidential', 'regulated');
  CREATE TYPE session_surface        AS ENUM (
    'owui', 'mattermost', 'teams', 'slack', 'api', 'email', 'sms', 'n8n'
  );
  CREATE TYPE session_security_tier  AS ENUM (
    'T0','T1','T2','T3','T4','T5','T6','T7'
  );
  CREATE TYPE session_tier_source    AS ENUM ('tenant', 'manifest', 'classification');
  CREATE TYPE tombstone_reason       AS ENUM (
    'retention_expired', 'gdpr_rte', 'tenant_offboarded', 'legal_order'
  );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;


-- -----------------------------------------------------------------------------
-- sessions — canonical session objects
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS sessions (
  session_id               UUID         PRIMARY KEY,
  tenant_id                TEXT         NOT NULL,
  agent_manifest_id        TEXT         NOT NULL,
  manifest_hash            TEXT         NOT NULL,     -- sha256 hex, pinned for life

  initiator_user_id        TEXT         NOT NULL,     -- Keycloak sub at creation

  owner_type               session_owner_type    NOT NULL,
  owner_user_id            TEXT,
  owner_group_id           TEXT,
  owner_agent_id           TEXT,
  owner_system_reason      session_system_reason,

  current_surface          session_surface       NOT NULL,
  surface_ref              TEXT,

  state                    session_state         NOT NULL DEFAULT 'active',
  classification           session_classification NOT NULL DEFAULT 'general',

  security_tier            session_security_tier NOT NULL,
  security_tier_source     session_tier_source   NOT NULL,
  retention_floor_days     INT          NOT NULL,
  retention_cap_days       INT,
  legal_hold               BOOLEAN      NOT NULL DEFAULT FALSE,
  legal_hold_reason        TEXT,

  expires_hot_at           TIMESTAMPTZ  NOT NULL,
  expires_cold_at          TIMESTAMPTZ  NOT NULL,
  kms_data_key_id          TEXT         NOT NULL,
  destroyed_at             TIMESTAMPTZ,

  data_region              TEXT         NOT NULL,

  forked_from_session_id   UUID,
  source_tenant_id         TEXT,
  fork_correlation_id      UUID,

  policy_context           JSONB        NOT NULL,      -- frozen OPA input snapshot
  participants             JSONB        NOT NULL DEFAULT '[]'::jsonb,
  transcript_head_hash     TEXT,                        -- points at last chain entry
  event_seq                BIGINT       NOT NULL DEFAULT 0,

  total_tokens             BIGINT       NOT NULL DEFAULT 0,
  total_cost_usd           NUMERIC(18,6) NOT NULL DEFAULT 0,

  created_at               TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at               TIMESTAMPTZ  NOT NULL DEFAULT now(),
  closed_at                TIMESTAMPTZ,

  -- Exactly one owner field is non-null and it must match owner_type.
  CONSTRAINT sessions_owner_consistent CHECK (
       (owner_type = 'user'   AND owner_user_id       IS NOT NULL AND owner_group_id IS NULL AND owner_agent_id IS NULL AND owner_system_reason IS NULL)
    OR (owner_type = 'group'  AND owner_group_id      IS NOT NULL AND owner_user_id  IS NULL AND owner_agent_id IS NULL AND owner_system_reason IS NULL)
    OR (owner_type = 'agent'  AND owner_agent_id      IS NOT NULL AND owner_user_id  IS NULL AND owner_group_id IS NULL AND owner_system_reason IS NULL)
    OR (owner_type = 'system' AND owner_system_reason IS NOT NULL AND owner_user_id  IS NULL AND owner_group_id IS NULL AND owner_agent_id      IS NULL)
  ),
  -- Retention invariants
  CONSTRAINT sessions_retention_non_negative CHECK (retention_floor_days >= 0),
  CONSTRAINT sessions_retention_cap_ge_floor CHECK (
    retention_cap_days IS NULL OR retention_cap_days >= retention_floor_days
  ),
  -- Cross-tenant fork coherence
  CONSTRAINT sessions_fork_refs_together CHECK (
       (forked_from_session_id IS NULL AND source_tenant_id IS NULL AND fork_correlation_id IS NULL)
    OR (forked_from_session_id IS NOT NULL AND source_tenant_id IS NOT NULL AND fork_correlation_id IS NOT NULL)
  )
);

CREATE INDEX IF NOT EXISTS sessions_tenant_state_idx         ON sessions (tenant_id, state);
CREATE INDEX IF NOT EXISTS sessions_owner_user_idx           ON sessions (owner_user_id)  WHERE owner_type = 'user';
CREATE INDEX IF NOT EXISTS sessions_owner_group_idx          ON sessions (owner_group_id) WHERE owner_type = 'group';
CREATE INDEX IF NOT EXISTS sessions_owner_agent_idx          ON sessions (owner_agent_id) WHERE owner_type = 'agent';
CREATE INDEX IF NOT EXISTS sessions_expires_hot_idx          ON sessions (expires_hot_at);
CREATE INDEX IF NOT EXISTS sessions_expires_cold_idx         ON sessions (expires_cold_at);
CREATE INDEX IF NOT EXISTS sessions_fork_correlation_idx     ON sessions (fork_correlation_id);
CREATE INDEX IF NOT EXISTS sessions_legal_hold_idx           ON sessions (legal_hold)     WHERE legal_hold = TRUE;
CREATE INDEX IF NOT EXISTS sessions_manifest_idx             ON sessions (agent_manifest_id, manifest_hash);


-- -----------------------------------------------------------------------------
-- session_bindings — surface attachments (OWUI chat, Slack thread, etc.)
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS session_bindings (
  binding_id         UUID         PRIMARY KEY,
  session_id         UUID         NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
  tenant_id          TEXT         NOT NULL,
  surface            session_surface NOT NULL,
  surface_ref        TEXT         NOT NULL,
  adapter_version    TEXT         NOT NULL,
  is_primary         BOOLEAN      NOT NULL DEFAULT FALSE,
  bound_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
  unbound_at         TIMESTAMPTZ,
  unbound_reason     TEXT,
  last_heartbeat_at  TIMESTAMPTZ
);

-- A live surface_ref cannot be pointed at by two sessions concurrently.
CREATE UNIQUE INDEX IF NOT EXISTS session_bindings_live_surface_uq
  ON session_bindings (tenant_id, surface, surface_ref)
  WHERE unbound_at IS NULL;

-- Exactly one primary binding per active session.
CREATE UNIQUE INDEX IF NOT EXISTS session_bindings_one_primary
  ON session_bindings (session_id)
  WHERE unbound_at IS NULL AND is_primary = TRUE;

CREATE INDEX IF NOT EXISTS session_bindings_session_idx ON session_bindings (session_id);
CREATE INDEX IF NOT EXISTS session_bindings_heartbeat_idx ON session_bindings (last_heartbeat_at)
  WHERE unbound_at IS NULL;


-- -----------------------------------------------------------------------------
-- session_events — append-only hash-chained event log
-- -----------------------------------------------------------------------------
-- Extends the existing governance-hub audit chain; prev_hash points at the
-- previous governance event for this session (or the tenant chain head when
-- the session is created). self_hash = sha256(prev_hash || canonical_json(event)).
--
-- Transcript content rides in payload_encrypted (per-session data key from
-- KMS). Metadata (actor, policy decision id, surface, etc.) stays in
-- payload_metadata so searches + observability work after cryptographic erasure.

CREATE TABLE IF NOT EXISTS session_events (
  event_id            UUID         PRIMARY KEY,
  session_id          UUID         NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
  tenant_id           TEXT         NOT NULL,     -- denormalized for residency filtering
  event_seq           BIGINT       NOT NULL,     -- strict per-session ordering
  event_type          TEXT         NOT NULL,     -- e.g. session.owner_change
  actor_sub           TEXT,                       -- Keycloak sub of actor (null for system)
  actor_type          TEXT         NOT NULL,     -- user | agent | system | adapter
  surface             session_surface,

  prev_hash           TEXT         NOT NULL,
  self_hash           TEXT         NOT NULL,

  payload_metadata    JSONB        NOT NULL,      -- unencrypted (policy decisions, refs)
  payload_encrypted   BYTEA,                      -- per-session data key (KMS wrapped)

  created_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),

  UNIQUE (session_id, event_seq)
);

CREATE INDEX IF NOT EXISTS session_events_session_seq_idx ON session_events (session_id, event_seq);
CREATE INDEX IF NOT EXISTS session_events_type_idx        ON session_events (event_type);
CREATE INDEX IF NOT EXISTS session_events_actor_idx       ON session_events (actor_sub)
  WHERE actor_sub IS NOT NULL;
CREATE INDEX IF NOT EXISTS session_events_created_idx     ON session_events (created_at);


-- -----------------------------------------------------------------------------
-- tombstones — post-destruction audit record (never deleted)
-- -----------------------------------------------------------------------------
-- Survives cryptographic erasure. Proves the session existed, summarizes
-- metadata, and links to the final chain head hash so auditors can verify
-- both existence and destruction without content recovery.

CREATE TABLE IF NOT EXISTS tombstones (
  tombstone_id           UUID         PRIMARY KEY,
  session_id             UUID         NOT NULL UNIQUE,   -- sessions row is gone post-erase
  tenant_id              TEXT         NOT NULL,

  created_at             TIMESTAMPTZ  NOT NULL,
  closed_at              TIMESTAMPTZ  NOT NULL,
  destroyed_at           TIMESTAMPTZ  NOT NULL,

  security_tier          session_security_tier NOT NULL,
  owner_trail_summary    TEXT         NOT NULL,
  participant_subs       TEXT[]       NOT NULL,          -- tenant-salted hash of Keycloak sub
  manifest_id            TEXT         NOT NULL,
  manifest_hash          TEXT         NOT NULL,

  event_count            INT          NOT NULL,
  message_count          INT          NOT NULL,
  attachment_count       INT          NOT NULL,
  total_tokens           BIGINT       NOT NULL,
  total_cost_usd         NUMERIC(18,6) NOT NULL,

  final_chain_head_hash  TEXT         NOT NULL,
  destruction_reason     tombstone_reason NOT NULL,
  destruction_actor_sub  TEXT,
  legal_basis_ref        TEXT
);

CREATE INDEX IF NOT EXISTS tombstones_destroyed_idx    ON tombstones (destroyed_at);
CREATE INDEX IF NOT EXISTS tombstones_closed_idx       ON tombstones (closed_at);
CREATE INDEX IF NOT EXISTS tombstones_manifest_idx     ON tombstones (manifest_hash);
CREATE INDEX IF NOT EXISTS tombstones_participants_gin ON tombstones USING GIN (participant_subs);
CREATE INDEX IF NOT EXISTS tombstones_tier_idx         ON tombstones (security_tier);


-- -----------------------------------------------------------------------------
-- push_subscriptions — Web Push endpoints per user/device
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS push_subscriptions (
  subscription_id       UUID         PRIMARY KEY,
  tenant_id             TEXT         NOT NULL,
  user_id               TEXT         NOT NULL,     -- Keycloak sub
  endpoint              TEXT         NOT NULL,
  p256dh_key            TEXT         NOT NULL,
  auth_key              TEXT         NOT NULL,
  device_attestation    JSONB,                     -- WebAuthn attestation (required T4+)
  allowed_tiers         session_security_tier[] NOT NULL DEFAULT ARRAY['T1','T2','T3']::session_security_tier[],
  created_at            TIMESTAMPTZ  NOT NULL DEFAULT now(),
  last_success_at       TIMESTAMPTZ,
  last_failure_at       TIMESTAMPTZ,
  revoked_at            TIMESTAMPTZ,
  revoked_reason        TEXT,

  UNIQUE (user_id, endpoint)
);

CREATE INDEX IF NOT EXISTS push_subs_user_idx ON push_subscriptions (user_id) WHERE revoked_at IS NULL;


-- -----------------------------------------------------------------------------
-- session_cost — materialized aggregate (refreshed every 60s)
-- -----------------------------------------------------------------------------
-- Used by portfolio dashboard + chargeback reports. Survives session
-- destruction by design (cost rollups never erased).

CREATE MATERIALIZED VIEW IF NOT EXISTS session_cost AS
SELECT
  s.tenant_id,
  s.session_id,
  s.agent_manifest_id,
  s.manifest_hash,
  s.initiator_user_id,
  s.security_tier,
  s.created_at,
  s.closed_at,
  s.total_tokens,
  s.total_cost_usd
FROM sessions s
WITH NO DATA;

CREATE INDEX IF NOT EXISTS session_cost_tenant_idx ON session_cost (tenant_id, created_at);
CREATE INDEX IF NOT EXISTS session_cost_agent_idx  ON session_cost (agent_manifest_id);


-- -----------------------------------------------------------------------------
-- updated_at trigger
-- -----------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION _sessions_touch_updated() RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS sessions_touch_updated ON sessions;
CREATE TRIGGER sessions_touch_updated
  BEFORE UPDATE ON sessions
  FOR EACH ROW EXECUTE FUNCTION _sessions_touch_updated();

COMMIT;
