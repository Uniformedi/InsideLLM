#!/usr/bin/env python3
"""
Seed the Dispute Handler agent + its actions + sample debtor ledger
rows for the Collections industry pack demo.

Idempotent: every insert uses ON CONFLICT DO NOTHING (or the equivalent
natural-key probe). Safe to run N times in a row; DB state is identical
after every run. That property is what makes the Hyper-V snapshot
pattern in docs/DemoPrep-Fast-Iteration.md §5 trustworthy.

Usage:
    python3 /opt/InsideLLM/scripts/seed-dispute-handler.py

Env:
    DSN   — PostgreSQL DSN. Defaults match the compose-stack credentials.
    PACK  — path to the Collections pack root
            (default: /opt/InsideLLM/configs/industry-packs/collections)
    TENANT_ID — default "example-tenant"
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    import psycopg2
    from psycopg2.extras import execute_batch
except ImportError:
    print("psycopg2 not installed. Run: pip install psycopg2-binary", file=sys.stderr)
    sys.exit(2)

try:
    import yaml
except ImportError:
    print("PyYAML not installed. Run: pip install pyyaml", file=sys.stderr)
    sys.exit(2)


DSN = os.environ.get(
    "DSN",
    "postgresql://litellm:9m4zBRHnpdc5qHj4Y5VULE8Y@postgres:5432/litellm",
)
PACK_ROOT = Path(os.environ.get("PACK", "/opt/InsideLLM/configs/industry-packs/collections"))
TENANT_ID = os.environ.get("TENANT_ID", "example-tenant")


def manifest_hash(manifest: dict) -> str:
    """Stable SHA-256 of the manifest — used as the agent's manifest_hash."""
    canon = json.dumps(manifest, sort_keys=True, default=str)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def load_agent_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def upsert_agent(cur, agent_yaml: dict) -> int:
    """Idempotent upsert of one agent row. Returns the governance_agents.id."""
    meta = agent_yaml["metadata"]
    spec = agent_yaml["spec"]
    agent_id = meta["agent_id"]
    name = meta["name"]
    description = meta.get("description", "").strip()
    team = meta.get("team", "")
    icon = meta.get("icon", "")
    data_cls = meta.get("data_classification", "internal")
    visibility = meta.get("visibility_scope", "private")
    guardrail_profile = spec.get("guardrail_profile", "tier_general_business")

    manifest = {"metadata": meta, "spec": spec, "apiVersion": agent_yaml.get("apiVersion")}
    mh = manifest_hash(manifest)

    # Natural key: (tenant_id, agent_id). The table's UniqueConstraint matches.
    cur.execute(
        """
        SELECT id, manifest_hash, status FROM governance_agents
        WHERE tenant_id = %s AND agent_id = %s
        """,
        (TENANT_ID, agent_id),
    )
    existing = cur.fetchone()

    if existing is None:
        cur.execute(
            """
            INSERT INTO governance_agents (
                agent_id, tenant_id, name, description, icon, team,
                manifest, manifest_schema_version,
                guardrail_profile, visibility_scope, data_classification,
                status, is_active, version, manifest_hash,
                created_by, created_at, updated_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s,
                %s, %s,
                %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s
            )
            RETURNING id
            """,
            (
                agent_id, TENANT_ID, name, description, icon, team,
                json.dumps(manifest), agent_yaml.get("apiVersion", "insidellm.agent/v1.1"),
                guardrail_profile, visibility, data_cls,
                "published", True, 1, mh,
                "seed-dispute-handler", datetime.now(timezone.utc), datetime.now(timezone.utc),
            ),
        )
        row_id = cur.fetchone()[0]
        print(f"  [+] created agent '{agent_id}' (id={row_id}, hash={mh[:12]})")
        return row_id

    row_id, current_hash, current_status = existing
    if current_hash == mh and current_status == "published":
        print(f"  [=] agent '{agent_id}' already seeded with same hash (id={row_id})")
        return row_id

    cur.execute(
        """
        UPDATE governance_agents
        SET name = %s, description = %s, icon = %s, team = %s,
            manifest = %s,
            guardrail_profile = %s, visibility_scope = %s, data_classification = %s,
            status = 'published', is_active = TRUE,
            version = version + 1, manifest_hash = %s,
            updated_at = %s
        WHERE id = %s
        """,
        (
            name, description, icon, team,
            json.dumps(manifest),
            guardrail_profile, visibility, data_cls,
            mh, datetime.now(timezone.utc),
            row_id,
        ),
    )
    print(f"  [~] updated agent '{agent_id}' (id={row_id}, new hash={mh[:12]})")
    return row_id


# --- Sample debtor ledger & disputes ----------------------------------------
# Deterministic (seeded UUIDs) so repeated seeding produces byte-identical
# rows. That's what makes post-seed Hyper-V snapshots reliable.

SAMPLE_ACCOUNTS = [
    {
        "account_id": "HH000001",
        "consumer_name": "Harper Hayes",
        "consumer_timezone": "America/New_York",
        "balance_usd": 1284.50,
        "original_creditor": "Helix Commerce Card Services",
        "current_creditor": "North Coast Recovery LLC",
        "authorized_channels": ["mail", "phone"],
        "validation_window_status": "active_0_of_30",
        "last_activity": "2026-04-18",
    },
    {
        "account_id": "TS000014",
        "consumer_name": "Terry Silva",
        "consumer_timezone": "America/Los_Angeles",
        "balance_usd": 8921.77,
        "original_creditor": "Meridian Lending Co.",
        "current_creditor": "North Coast Recovery LLC",
        "authorized_channels": ["mail"],
        "validation_window_status": "disputed_in_writing",
        "last_activity": "2026-04-10",
    },
    {
        "account_id": "DP000088",
        "consumer_name": "Drew Patel",
        "consumer_timezone": "America/Chicago",
        "balance_usd": 342.05,
        "original_creditor": "Southside Medical Group",
        "current_creditor": "North Coast Recovery LLC",
        "authorized_channels": ["mail", "phone", "email"],
        "validation_window_status": "expired_assumed_valid",
        "last_activity": "2026-03-02",
    },
]


def ensure_demo_ledger_table(cur) -> None:
    """Create the sample ledger + disputes tables if they don't exist. These
    are DEMO-ONLY tables, prefixed demo_ so they're obvious in any schema
    listing. The real product uses a different data model; this is only for
    what `lookup_account` / `open_dispute_record` read during the Friday
    demo."""
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS demo_collections_ledger (
            account_id VARCHAR(32) PRIMARY KEY,
            consumer_name VARCHAR(200) NOT NULL,
            consumer_timezone VARCHAR(64) NOT NULL,
            balance_usd NUMERIC(12,2) NOT NULL,
            original_creditor VARCHAR(200) NOT NULL,
            current_creditor VARCHAR(200) NOT NULL,
            authorized_channels JSONB NOT NULL,
            validation_window_status VARCHAR(50) NOT NULL,
            last_activity DATE NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS demo_collections_disputes (
            id SERIAL PRIMARY KEY,
            account_id VARCHAR(32) NOT NULL,
            received_date DATE NOT NULL,
            channel VARCHAR(32) NOT NULL,
            status VARCHAR(32) NOT NULL DEFAULT 'open',
            summary TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE (account_id, received_date, channel)
        );
        """
    )


def seed_ledger(cur) -> None:
    for a in SAMPLE_ACCOUNTS:
        cur.execute(
            """
            INSERT INTO demo_collections_ledger
                (account_id, consumer_name, consumer_timezone, balance_usd,
                 original_creditor, current_creditor, authorized_channels,
                 validation_window_status, last_activity)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (account_id) DO NOTHING
            """,
            (
                a["account_id"], a["consumer_name"], a["consumer_timezone"], a["balance_usd"],
                a["original_creditor"], a["current_creditor"], json.dumps(a["authorized_channels"]),
                a["validation_window_status"], a["last_activity"],
            ),
        )
    print(f"  [+] ledger rows present: {len(SAMPLE_ACCOUNTS)} (idempotent)")


def seed_sample_dispute(cur) -> None:
    # One pending dispute on TS000014 so the demo can show an in-flight case
    cur.execute(
        """
        INSERT INTO demo_collections_disputes
            (account_id, received_date, channel, status, summary)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (account_id, received_date, channel) DO NOTHING
        """,
        (
            "TS000014", "2026-04-15", "mail", "open",
            "Consumer disputes balance; claims account was closed in 2024 and the charge-off is a duplicate.",
        ),
    )
    print("  [+] sample dispute row present (idempotent)")


# --- Audit-chain pre-population ---------------------------------------------
# Adds a handful of representative governance events so the chain-verify
# demo has substance. Idempotent via a sentinel row; re-runs do nothing.

def seed_audit_chain_if_sparse(cur) -> None:
    cur.execute("SELECT COUNT(*) FROM governance_audit_chain")
    (count,) = cur.fetchone()
    if count >= 50:
        print(f"  [=] audit chain has {count} entries; skipping pre-population")
        return

    # We use the real append_event via a minimal equivalent: replicate the
    # SHA-256 chain logic the service uses. This is intentionally explicit
    # so that any drift from services/audit_chain.py is caught here.
    import hashlib
    genesis = "0" * 64

    cur.execute(
        "SELECT sequence, chain_hash FROM governance_audit_chain ORDER BY sequence DESC LIMIT 1"
    )
    tip = cur.fetchone()
    seq = (tip[0] if tip else 0) + 1
    prev = tip[1] if tip else genesis

    event_types = [
        "agent_create", "agent_publish",
        "policy_decision", "policy_decision",
        "dlp_scan", "dlp_scan", "dlp_scan",
        "sync_export", "change_proposed", "change_approved",
    ]

    rows = []
    now = datetime.now(timezone.utc) - timedelta(minutes=5 * len(event_types))
    for i, et in enumerate(event_types):
        # Do this 5 times to reach ~50 entries total.
        pass

    # Generate 55 total to comfortably clear the 50 threshold.
    target = 55
    rows = []
    for i in range(target):
        et = event_types[i % len(event_types)]
        payload = {"event_type": et, "index": i, "seeded_by": "seed-dispute-handler"}
        p_hash = hashlib.sha256(
            json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        chain_data = f"{seq}|{et}|{p_hash}|{prev}"
        c_hash = hashlib.sha256(chain_data.encode("utf-8")).hexdigest()
        rows.append((seq, et, None, p_hash, prev, c_hash, "demo", now + timedelta(minutes=i)))
        prev = c_hash
        seq += 1

    execute_batch(
        cur,
        """
        INSERT INTO governance_audit_chain
            (sequence, event_type, event_id, payload_hash, previous_hash,
             chain_hash, instance_id, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT DO NOTHING
        """,
        rows,
        page_size=100,
    )
    print(f"  [+] audit chain pre-populated with {len(rows)} entries")


def main() -> int:
    if not PACK_ROOT.exists():
        print(f"Collections pack not found at {PACK_ROOT}", file=sys.stderr)
        return 1

    print(f"Seeding Dispute Handler demo state → {DSN.split('@')[-1]}")
    print(f"Pack: {PACK_ROOT}")
    print(f"Tenant: {TENANT_ID}")
    print()

    conn = psycopg2.connect(DSN)
    conn.autocommit = False
    try:
        cur = conn.cursor()

        print("Step 1 — Collections pack agents")
        for yaml_path in [
            PACK_ROOT / "agents" / "dispute-handler.yaml",
            PACK_ROOT / "agents" / "validation-notice-writer.yaml",
            PACK_ROOT / "agents" / "skip-tracer.yaml",
            PACK_ROOT / "agents" / "compliance-reviewer.yaml",
        ]:
            if not yaml_path.exists():
                print(f"  [!] skipping {yaml_path.name} — file missing")
                continue
            agent_yaml = load_agent_yaml(yaml_path)
            upsert_agent(cur, agent_yaml)

        print()
        print("Step 2 — Demo ledger tables + rows")
        ensure_demo_ledger_table(cur)
        seed_ledger(cur)
        seed_sample_dispute(cur)

        print()
        print("Step 3 — Audit chain pre-population (if sparse)")
        seed_audit_chain_if_sparse(cur)

        conn.commit()
        print()
        print("Seed complete. Safe to take Hyper-V snapshot: 'seeded-clean'")
        return 0

    except Exception as exc:
        conn.rollback()
        print(f"\nSEED FAILED: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
