"""Canonical session service.

Encapsulates creation, ownership transitions, and hash-chained event append
for canonical sessions. All policy questions (handoff eligibility, retention
validity, residency, federation, mirror promotion) are delegated to OPA;
this module composes the OPA input, calls OPA, and — on allow — performs
the DB mutation + processes any obligations returned.

Design rules:
  * OPA is pure. It returns {deny_reasons, obligations}. We never read OPA
    for side effects; we act on obligations here.
  * Session events extend a per-session hash chain rooted in a tenant-anchored
    genesis. The chain head is anchored into the governance-hub audit chain
    via `audit_chain.append_event` on session open, close, and destruction.
  * Ownership transitions are serialized per session via Postgres advisory
    locks (`pg_advisory_xact_lock(hashtext(session_id))`).

Not implemented in this cut:
  * Surface-specific notification fan-out (delegated to adapters).
  * Cryptographic erasure at retention expiry (ships in 3.3.1 as a scheduled
    job that walks `expires_cold_at`).
  * Federated token exchange for cross-tenant forks (ships in 4.3).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from . import audit_chain

logger = logging.getLogger("governance-hub.sessions.service")

OPA_URL = os.environ.get("OPA_URL", "http://opa:8181")
_OPA_TIMEOUT = httpx.Timeout(5.0, connect=2.0)

# Session-chain genesis: tenant-scoped so cross-tenant replay is impossible.
_SESSION_GENESIS_PREFIX = "insidellm.session.v1:"

OwnerType = Literal["user", "group", "agent", "system"]


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Actor:
    sub: str
    roles: tuple[str, ...]
    auth_method: str = "oidc"


@dataclass(frozen=True)
class HandoffTarget:
    type: OwnerType
    ref: str
    tenant_id: str | None = None
    status: str = "online"
    roles: tuple[str, ...] = ()


@dataclass(frozen=True)
class OpaDecision:
    allowed: bool
    deny_reasons: tuple[str, ...]
    obligations: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class AppendResult:
    event_id: uuid.UUID
    event_seq: int
    self_hash: str


# ---------------------------------------------------------------------------
# Hash chain primitives
# ---------------------------------------------------------------------------


def _session_genesis_hash(tenant_id: str, session_id: uuid.UUID) -> str:
    seed = f"{_SESSION_GENESIS_PREFIX}{tenant_id}:{session_id}".encode("utf-8")
    return hashlib.sha256(seed).hexdigest()


def _canonical_json(payload: Any) -> bytes:
    return json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")


def _next_self_hash(prev_hash: str, event: dict[str, Any]) -> str:
    h = hashlib.sha256()
    h.update(prev_hash.encode("utf-8"))
    h.update(b"|")
    h.update(_canonical_json(event))
    return h.hexdigest()


# ---------------------------------------------------------------------------
# OPA client
# ---------------------------------------------------------------------------


async def _opa_query(package_path: str, opa_input: dict[str, Any]) -> OpaDecision:
    """POST to OPA's data API; return a uniform decision."""
    url = f"{OPA_URL}/v1/data/{package_path}"
    try:
        async with httpx.AsyncClient(timeout=_OPA_TIMEOUT) as client:
            resp = await client.post(url, json={"input": opa_input})
            resp.raise_for_status()
            body = resp.json()
    except httpx.HTTPError as e:
        # Fail-closed: if OPA is unreachable, deny.
        logger.error("OPA query failed: %s", e)
        return OpaDecision(
            allowed=False,
            deny_reasons=(f"opa_unreachable: {type(e).__name__}",),
            obligations=(),
        )

    result = body.get("result") or {}
    deny_reasons = tuple(result.get("deny_reasons") or ())
    obligations = tuple(result.get("obligations") or ())
    return OpaDecision(
        allowed=len(deny_reasons) == 0,
        deny_reasons=deny_reasons,
        obligations=obligations,
    )


# ---------------------------------------------------------------------------
# Advisory lock
# ---------------------------------------------------------------------------


async def _lock_session(db: AsyncSession, session_id: uuid.UUID) -> None:
    """Serialize mutations on a session within the current transaction."""
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:sid))"),
        {"sid": str(session_id)},
    )


# ---------------------------------------------------------------------------
# Session event append (per-session hash chain)
# ---------------------------------------------------------------------------


async def append_session_event(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    tenant_id: str,
    event_type: str,
    actor_type: Literal["user", "agent", "system", "adapter"],
    actor_sub: str | None,
    surface: str | None,
    payload_metadata: dict[str, Any],
    payload_encrypted: bytes | None = None,
) -> AppendResult:
    """Append a hash-chained event to session_events and bump event_seq."""
    await _lock_session(db, session_id)

    row = (
        await db.execute(
            text(
                "SELECT event_seq, transcript_head_hash FROM sessions WHERE session_id = :sid FOR UPDATE"
            ),
            {"sid": str(session_id)},
        )
    ).first()
    if row is None:
        raise LookupError(f"session not found: {session_id}")

    prev_seq, prev_hash = row
    prev_hash = prev_hash or _session_genesis_hash(tenant_id, session_id)
    next_seq = (prev_seq or 0) + 1
    event_id = uuid.uuid4()

    event_body = {
        "event_id": str(event_id),
        "session_id": str(session_id),
        "tenant_id": tenant_id,
        "event_seq": next_seq,
        "event_type": event_type,
        "actor_type": actor_type,
        "actor_sub": actor_sub,
        "surface": surface,
        "payload_metadata": payload_metadata,
    }
    self_hash = _next_self_hash(prev_hash, event_body)

    await db.execute(
        text(
            """
            INSERT INTO session_events (
                event_id, session_id, tenant_id, event_seq, event_type,
                actor_sub, actor_type, surface,
                prev_hash, self_hash,
                payload_metadata, payload_encrypted
            ) VALUES (
                :event_id, :session_id, :tenant_id, :event_seq, :event_type,
                :actor_sub, :actor_type, :surface,
                :prev_hash, :self_hash,
                CAST(:payload_metadata AS jsonb), :payload_encrypted
            )
            """
        ),
        {
            "event_id": str(event_id),
            "session_id": str(session_id),
            "tenant_id": tenant_id,
            "event_seq": next_seq,
            "event_type": event_type,
            "actor_sub": actor_sub,
            "actor_type": actor_type,
            "surface": surface,
            "prev_hash": prev_hash,
            "self_hash": self_hash,
            "payload_metadata": json.dumps(payload_metadata),
            "payload_encrypted": payload_encrypted,
        },
    )

    await db.execute(
        text(
            "UPDATE sessions SET event_seq = :seq, transcript_head_hash = :h WHERE session_id = :sid"
        ),
        {"seq": next_seq, "h": self_hash, "sid": str(session_id)},
    )

    return AppendResult(event_id=event_id, event_seq=next_seq, self_hash=self_hash)


# ---------------------------------------------------------------------------
# Obligation handler
# ---------------------------------------------------------------------------


async def _apply_obligations(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    tenant_id: str,
    actor: Actor,
    obligations: tuple[dict[str, Any], ...],
    surface: str | None,
) -> None:
    """Enforce each obligation. Unknown types log + skip (fail-soft on enforcement)."""
    for ob in sorted(obligations, key=lambda o: o.get("priority", 99)):
        kind = ob.get("type")
        params = ob.get("params", {}) or {}
        if kind == "audit.log":
            await append_session_event(
                db,
                session_id=session_id,
                tenant_id=tenant_id,
                event_type=params.get("event_type", "session.audit"),
                actor_type="user" if actor else "system",
                actor_sub=actor.sub if actor else None,
                surface=surface,
                payload_metadata={"obligation": "audit.log", **params},
            )
        elif kind == "session.quarantine":
            await db.execute(
                text("UPDATE sessions SET state = 'quarantined' WHERE session_id = :sid"),
                {"sid": str(session_id)},
            )
            await append_session_event(
                db,
                session_id=session_id,
                tenant_id=tenant_id,
                event_type="session.quarantined",
                actor_type="system",
                actor_sub=None,
                surface=None,
                payload_metadata=params,
            )
        elif kind == "token.revoke":
            # Delegated to session_token_exchange service (not implemented
            # in this cut). We record the obligation in the chain so recovery
            # can replay it when the token layer lands.
            await append_session_event(
                db,
                session_id=session_id,
                tenant_id=tenant_id,
                event_type="session.token_revoke_scheduled",
                actor_type="system",
                actor_sub=None,
                surface=surface,
                payload_metadata=params,
            )
        elif kind in {
            "dlp.rescan",
            "compliance.fdcpa_access_log",
            "compliance.hipaa_access_log",
            "compliance.sox_17a4_change_record",
            "identity.federated_sub",
            "token.exchange",
        }:
            # These belong to downstream services. Record the intent; the
            # receiver picks it up via LISTEN/NOTIFY on session_events.
            await append_session_event(
                db,
                session_id=session_id,
                tenant_id=tenant_id,
                event_type=f"obligation.{kind}",
                actor_type="system",
                actor_sub=None,
                surface=surface,
                payload_metadata={"params": params},
            )
        else:
            logger.warning("unknown obligation type: %s", kind)


# ---------------------------------------------------------------------------
# Tier defaults
# ---------------------------------------------------------------------------

# (hot_days, cold_days, max_total_days) — matches retention.rego
TIER_DEFAULTS: dict[str, tuple[int, int, int]] = {
    "T0": (1, 0, 1),
    "T1": (30, 0, 30),
    "T2": (90, 365, 455),
    "T3": (30, 1095, 1125),
    "T4": (60, 2495, 2555),
    "T5": (30, 2160, 2190),
    "T6": (30, 2525, 2555),
    "T7": (7, 0, 7),
}


def _expiry_bounds(
    tier: str,
    now: datetime,
    floor_override_days: int = 0,
    cap_override_days: int = 0,
) -> tuple[datetime, datetime]:
    hot, cold, total = TIER_DEFAULTS.get(tier, TIER_DEFAULTS["T2"])
    if floor_override_days:
        total = max(total, floor_override_days)
    if cap_override_days:
        total = min(total, cap_override_days)
    return now + timedelta(days=hot), now + timedelta(days=total)


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


async def create_session(
    db: AsyncSession,
    *,
    tenant_id: str,
    agent_manifest_id: str,
    manifest_hash: str,
    initiator: Actor,
    surface: str,
    surface_ref: str | None,
    classification: str = "general",
    security_tier: str = "T2",
    tier_source: str = "tenant",
    data_region: str = "us-east",
    kms_data_key_id: str,
    manifest_min_tier: str | None = None,
    classification_min_tier: str | None = None,
    retention_floor_override: int = 0,
    retention_cap_override: int = 0,
) -> dict[str, Any]:
    """Create a canonical session, anchored to a KMS data key.

    Effective tier = max(tenant_tier, manifest_min_tier, classification_min_tier).
    Retention is computed from the effective tier + optional overrides.
    """
    tiers = [t for t in (security_tier, manifest_min_tier, classification_min_tier) if t]
    effective_tier = max(tiers, key=lambda t: int(t[1:]))
    now = datetime.now(timezone.utc)
    hot_at, cold_at = _expiry_bounds(
        effective_tier, now, retention_floor_override, retention_cap_override
    )
    hot_days, _, total_days = TIER_DEFAULTS.get(effective_tier, TIER_DEFAULTS["T2"])
    floor_days = max(retention_floor_override, hot_days)

    session_id = uuid.uuid4()
    policy_context = {
        "tenant_id": tenant_id,
        "manifest_hash": manifest_hash,
        "agent_manifest_id": agent_manifest_id,
        "classification": classification,
        "effective_tier": effective_tier,
        "tier_source": tier_source,
    }

    await db.execute(
        text(
            """
            INSERT INTO sessions (
                session_id, tenant_id, agent_manifest_id, manifest_hash,
                initiator_user_id,
                owner_type, owner_user_id,
                current_surface, surface_ref,
                state, classification,
                security_tier, security_tier_source,
                retention_floor_days, retention_cap_days,
                expires_hot_at, expires_cold_at,
                kms_data_key_id, data_region,
                policy_context, participants
            ) VALUES (
                :sid, :tenant, :manifest_id, :manifest_hash,
                :initiator,
                'user', :initiator,
                :surface, :surface_ref,
                'active', :classification,
                :tier, :tier_source,
                :floor_days, :cap_days,
                :hot_at, :cold_at,
                :kms_key, :region,
                CAST(:ctx AS jsonb), CAST(:ppl AS jsonb)
            )
            """
        ),
        {
            "sid": str(session_id),
            "tenant": tenant_id,
            "manifest_id": agent_manifest_id,
            "manifest_hash": manifest_hash,
            "initiator": initiator.sub,
            "surface": surface,
            "surface_ref": surface_ref,
            "classification": classification,
            "tier": effective_tier,
            "tier_source": tier_source,
            "floor_days": floor_days,
            "cap_days": total_days,
            "hot_at": hot_at,
            "cold_at": cold_at,
            "kms_key": kms_data_key_id,
            "region": data_region,
            "ctx": json.dumps(policy_context),
            "ppl": json.dumps([{
                "user_id": initiator.sub,
                "role": "initiator",
                "from_ts": now.isoformat(),
            }]),
        },
    )

    if surface_ref:
        await db.execute(
            text(
                """
                INSERT INTO session_bindings (
                    binding_id, session_id, tenant_id, surface, surface_ref,
                    adapter_version, is_primary, bound_at, last_heartbeat_at
                ) VALUES (
                    :bid, :sid, :tenant, :surface, :surface_ref,
                    :adv, TRUE, :now, :now
                )
                """
            ),
            {
                "bid": str(uuid.uuid4()),
                "sid": str(session_id),
                "tenant": tenant_id,
                "surface": surface,
                "surface_ref": surface_ref,
                "adv": "3.3.0",
                "now": now,
            },
        )

    await append_session_event(
        db,
        session_id=session_id,
        tenant_id=tenant_id,
        event_type="session.created",
        actor_type="user",
        actor_sub=initiator.sub,
        surface=surface,
        payload_metadata={
            "manifest_id": agent_manifest_id,
            "manifest_hash": manifest_hash,
            "effective_tier": effective_tier,
            "classification": classification,
            "data_region": data_region,
        },
    )

    await audit_chain.append_event(
        db,
        event_type="session.created",
        event_id=None,
        payload={
            "session_id": str(session_id),
            "tenant_id": tenant_id,
            "tier": effective_tier,
        },
    )

    return {
        "session_id": str(session_id),
        "tier": effective_tier,
        "expires_hot_at": hot_at.isoformat(),
        "expires_cold_at": cold_at.isoformat(),
    }


# ---------------------------------------------------------------------------
# Retention expiry + tombstone
# ---------------------------------------------------------------------------


async def expire_cold_sessions(db: AsyncSession, *, now: datetime | None = None) -> int:
    """Walk sessions past expires_cold_at and emit a tombstone + destroy row.

    Actual KMS key revocation is delegated to the caller (pluggable). We
    record the intent and tombstone; the key-revoke obligation rides in the
    chain so a recovery run can detect unrevoked keys.
    """
    now = now or datetime.now(timezone.utc)
    rows = (
        await db.execute(
            text(
                """
                SELECT session_id, tenant_id, agent_manifest_id, manifest_hash,
                       security_tier, created_at, closed_at, participants,
                       event_seq, total_tokens, total_cost_usd,
                       transcript_head_hash, legal_hold
                  FROM sessions
                 WHERE expires_cold_at <= :now
                   AND destroyed_at IS NULL
                   AND legal_hold = FALSE
                 LIMIT 100
                """
            ),
            {"now": now},
        )
    ).all()

    produced = 0
    for r in rows:
        participants = r.participants or []
        trail = " -> ".join(
            f"{p.get('role', '?')}:{p.get('user_id', '?')}" for p in participants
        )
        tombstone_id = uuid.uuid4()
        await db.execute(
            text(
                """
                INSERT INTO tombstones (
                    tombstone_id, session_id, tenant_id,
                    created_at, closed_at, destroyed_at,
                    security_tier, owner_trail_summary, participant_subs,
                    manifest_id, manifest_hash,
                    event_count, message_count, attachment_count,
                    total_tokens, total_cost_usd,
                    final_chain_head_hash, destruction_reason
                ) VALUES (
                    :tid, :sid, :tenant,
                    :created, :closed, :now,
                    :tier, :trail, CAST(:subs AS TEXT[]),
                    :m_id, :m_hash,
                    :ev, 0, 0,
                    :tok, :cost,
                    :head, 'retention_expired'
                )
                """
            ),
            {
                "tid": str(tombstone_id),
                "sid": str(r.session_id),
                "tenant": r.tenant_id,
                "created": r.created_at,
                "closed": r.closed_at or now,
                "now": now,
                "tier": r.security_tier,
                "trail": trail[:1024],
                "subs": "{" + ",".join(
                    _hashed_sub(r.tenant_id, p.get("user_id", ""))
                    for p in participants
                    if p.get("user_id")
                ) + "}",
                "m_id": r.agent_manifest_id,
                "m_hash": r.manifest_hash,
                "ev": r.event_seq or 0,
                "tok": r.total_tokens or 0,
                "cost": r.total_cost_usd or 0,
                "head": r.transcript_head_hash or "",
            },
        )
        await db.execute(
            text(
                "UPDATE sessions SET destroyed_at = :now, state = 'archived' "
                "WHERE session_id = :sid"
            ),
            {"now": now, "sid": str(r.session_id)},
        )
        await audit_chain.append_event(
            db,
            event_type="session.destroyed",
            event_id=None,
            payload={
                "session_id": str(r.session_id),
                "tombstone_id": str(tombstone_id),
                "reason": "retention_expired",
            },
        )
        produced += 1

    return produced


def _hashed_sub(tenant_salt: str, sub: str) -> str:
    h = hashlib.sha256()
    h.update(tenant_salt.encode("utf-8"))
    h.update(b"|")
    h.update(sub.encode("utf-8"))
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Handoff
# ---------------------------------------------------------------------------


async def request_handoff(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    target: HandoffTarget,
    reason: str,
    actor: Actor,
    hop_count: int = 0,
    agent_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate handoff policy and — on allow — update ownership + chain."""
    await _lock_session(db, session_id)

    row = (
        await db.execute(
            text(
                """
                SELECT tenant_id, security_tier, classification, manifest_hash,
                       owner_type, owner_user_id, owner_group_id, owner_agent_id,
                       owner_system_reason, state, data_region
                FROM sessions WHERE session_id = :sid FOR UPDATE
                """
            ),
            {"sid": str(session_id)},
        )
    ).first()
    if row is None:
        raise LookupError(f"session not found: {session_id}")

    if row.state in {"closed", "archived", "forked_closed", "revoked_by_source"}:
        raise ValueError(f"session state {row.state} does not accept handoff")

    source_ref = (
        row.owner_user_id
        or row.owner_group_id
        or row.owner_agent_id
        or row.owner_system_reason
    )

    opa_input: dict[str, Any] = {
        "session": {
            "session_id": str(session_id),
            "tenant_id": row.tenant_id,
            "security_tier": row.security_tier,
            "classification": row.classification,
            "manifest_hash": row.manifest_hash,
        },
        "source": {"owner_type": row.owner_type, "owner_ref": source_ref},
        "target": {
            "type": target.type,
            "ref": target.ref,
            "tenant_id": target.tenant_id or row.tenant_id,
            "status": target.status,
            "roles": list(target.roles),
        },
        "actor": {"sub": actor.sub, "roles": list(actor.roles)},
        "agent": agent_meta or {"accepts_handoff": False, "handoff_chain_tags": []},
        "handoff": {"reason": reason, "hop_count": hop_count},
    }

    decision = await _opa_query("insidellm/sessions/handoff", opa_input)

    if not decision.allowed:
        # Record the denial event regardless, but don't change ownership.
        await append_session_event(
            db,
            session_id=session_id,
            tenant_id=row.tenant_id,
            event_type="session.handoff.denied",
            actor_type="user",
            actor_sub=actor.sub,
            surface=None,
            payload_metadata={
                "target": {"type": target.type, "ref": target.ref},
                "deny_reasons": list(decision.deny_reasons),
                "reason": reason,
            },
        )
        return {
            "allowed": False,
            "deny_reasons": list(decision.deny_reasons),
            "state": row.state,
        }

    # Apply ownership change
    owner_cols = {
        "owner_user_id": None,
        "owner_group_id": None,
        "owner_agent_id": None,
        "owner_system_reason": None,
    }
    if target.type == "user":
        owner_cols["owner_user_id"] = target.ref
    elif target.type == "group":
        owner_cols["owner_group_id"] = target.ref
    elif target.type == "agent":
        owner_cols["owner_agent_id"] = target.ref
    elif target.type == "system":
        owner_cols["owner_system_reason"] = target.ref

    await db.execute(
        text(
            """
            UPDATE sessions
               SET owner_type = :owner_type,
                   owner_user_id = :owner_user_id,
                   owner_group_id = :owner_group_id,
                   owner_agent_id = :owner_agent_id,
                   owner_system_reason = :owner_system_reason,
                   state = 'active'
             WHERE session_id = :sid
            """
        ),
        {"owner_type": target.type, "sid": str(session_id), **owner_cols},
    )

    # Hash-chain the transition
    await append_session_event(
        db,
        session_id=session_id,
        tenant_id=row.tenant_id,
        event_type="session.owner_change",
        actor_type="user",
        actor_sub=actor.sub,
        surface=None,
        payload_metadata={
            "from": {"type": row.owner_type, "ref": source_ref},
            "to": {"type": target.type, "ref": target.ref},
            "reason": reason,
            "manifest_hash": row.manifest_hash,
        },
    )

    # Honor obligations
    await _apply_obligations(
        db,
        session_id=session_id,
        tenant_id=row.tenant_id,
        actor=actor,
        obligations=decision.obligations,
        surface=None,
    )

    # Anchor the new chain head into the central governance audit chain.
    await audit_chain.append_event(
        db,
        event_type="session.handoff.authorized",
        event_id=None,
        payload={
            "session_id": str(session_id),
            "tenant_id": row.tenant_id,
            "from_owner_type": row.owner_type,
            "to_owner_type": target.type,
        },
    )

    return {
        "allowed": True,
        "deny_reasons": [],
        "state": "active",
        "current_owner": {"type": target.type, "ref": target.ref},
    }
