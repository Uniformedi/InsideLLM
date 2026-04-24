"""Unit tests for ReportUp — the opt-in governance-data share feature.

Covers the code I actually own:
  * canonical_json is deterministic (key-order, no whitespace, UTF-8)
  * compute_envelope_hash is hash-stable regardless of key order AND
    excludes envelope_hash + hmac_signature from the hash input
  * hmac_sign matches stdlib hmac bit-exactly
  * verify_envelope rejects: tampered payload, wrong secret, broken chain
  * verify_envelope accepts: correct payload + secret + chain
  * Router + UI page ship + contain required anchors (no runtime import —
    avoids pulling in the full RBAC/jose dep chain from other tests)
"""
from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path

import pytest

from src.services import reportup_service as r


# ---------------------------------------------------------------------------
# canonical_json
# ---------------------------------------------------------------------------


def test_canonical_json_is_deterministic_across_key_order():
    a = {"b": 2, "a": 1, "c": {"z": 1, "y": 2}}
    b = {"a": 1, "c": {"y": 2, "z": 1}, "b": 2}
    assert r.canonical_json(a) == r.canonical_json(b)


def test_canonical_json_has_no_whitespace():
    out = r.canonical_json({"k": "v", "n": 1})
    assert b" " not in out
    assert b"\n" not in out


def test_canonical_json_utf8_preserves_unicode():
    out = r.canonical_json({"name": "Harris & Harris §1692g"})
    assert "§" in out.decode("utf-8")


# ---------------------------------------------------------------------------
# compute_envelope_hash
# ---------------------------------------------------------------------------


def test_envelope_hash_stable_regardless_of_order():
    e1 = {"tenant_id": "t1", "sequence_from": 1, "previous_envelope_hash": None, "audit_chain": []}
    e2 = {"previous_envelope_hash": None, "audit_chain": [], "sequence_from": 1, "tenant_id": "t1"}
    assert r.compute_envelope_hash(e1) == r.compute_envelope_hash(e2)


def test_envelope_hash_excludes_hash_and_signature_fields():
    """If the hash field itself were included, nobody could reproduce it.
    Same for the signature. Regression guard: the hash function MUST
    strip both before hashing."""
    e = {"tenant_id": "t1", "audit_chain": [], "envelope_hash": "AAAA",
         "hmac_signature": "BBBB"}
    h1 = r.compute_envelope_hash(e)
    e2 = {**e, "envelope_hash": "ZZZZ", "hmac_signature": "QQQQ"}
    h2 = r.compute_envelope_hash(e2)
    assert h1 == h2, "hash must ignore envelope_hash + hmac_signature fields"


def test_envelope_hash_matches_sha256_of_canonical_bytes():
    e = {"tenant_id": "t1", "audit_chain": [{"sequence": 42}]}
    expected = hashlib.sha256(r.canonical_json(e)).hexdigest()
    assert r.compute_envelope_hash(e) == expected


# ---------------------------------------------------------------------------
# hmac_sign
# ---------------------------------------------------------------------------


def test_hmac_sign_matches_stdlib():
    secret = "s3cret-0123456789abcdef0123456789abcdef"
    env_hash = "a" * 64
    expected = hmac.new(secret.encode(), env_hash.encode(), hashlib.sha256).hexdigest()
    assert r.hmac_sign(secret, env_hash) == expected


def test_hmac_sign_different_secrets_produce_different_sigs():
    h = "a" * 64
    s1 = r.hmac_sign("secret1-" + "x" * 30, h)
    s2 = r.hmac_sign("secret2-" + "x" * 30, h)
    assert s1 != s2


# ---------------------------------------------------------------------------
# verify_envelope
# ---------------------------------------------------------------------------


def _make_valid_envelope(secret: str, previous_hash: str | None = None) -> dict:
    """Build an envelope the way run_once would: compute hash, sign it."""
    env = {
        "schema_version": "1.0",
        "tenant_id": "t1",
        "tenant_name": "Tenant One",
        "parent_name": "Parent Portfolio",
        "generated_at": "2026-04-21T00:00:00+00:00",
        "sequence_from": 1,
        "sequence_to": 5,
        "previous_envelope_hash": previous_hash,
        "audit_chain": [{"sequence": i, "event_type": "t", "payload_hash": "x",
                         "previous_hash": "y", "chain_hash": "z"}
                        for i in range(1, 6)],
        "telemetry": [],
        "agents": [],
        "identity_users": [],
        "identity_groups": [],
        "change_proposals": [],
    }
    env["envelope_hash"] = r.compute_envelope_hash(env)
    env["hmac_signature"] = r.hmac_sign(secret, env["envelope_hash"])
    return env


def test_verify_envelope_accepts_valid():
    secret = "a" * 48
    env = _make_valid_envelope(secret)
    ok, err = r.verify_envelope(env, secret=secret)
    assert ok is True
    assert err is None


def test_verify_envelope_rejects_tampered_payload():
    secret = "a" * 48
    env = _make_valid_envelope(secret)
    env["audit_chain"][0]["payload_hash"] = "MUTATED"   # alter payload
    ok, err = r.verify_envelope(env, secret=secret)
    assert ok is False
    assert err and "envelope_hash mismatch" in err


def test_verify_envelope_rejects_wrong_secret():
    env = _make_valid_envelope("correct-secret-" + "x" * 30)
    ok, err = r.verify_envelope(env, secret="wrong-secret-" + "y" * 30)
    assert ok is False
    assert err and "hmac_signature mismatch" in err


def test_verify_envelope_rejects_broken_chain():
    secret = "a" * 48
    env = _make_valid_envelope(secret, previous_hash="aa" * 32)
    ok, err = r.verify_envelope(env, secret=secret, expected_previous_hash="bb" * 32)
    assert ok is False
    assert err and "previous_envelope_hash mismatch" in err


def test_verify_envelope_accepts_matching_chain():
    secret = "a" * 48
    prev = "cc" * 32
    env = _make_valid_envelope(secret, previous_hash=prev)
    ok, err = r.verify_envelope(env, secret=secret, expected_previous_hash=prev)
    assert ok is True


# ---------------------------------------------------------------------------
# Router + UI file shipment (source-level, no runtime import)
# ---------------------------------------------------------------------------


REPO = Path(__file__).resolve().parents[3]


def test_router_source_defines_required_paths():
    src = (REPO / "configs" / "governance-hub" / "src" / "routers" / "reportup.py").read_text(encoding="utf-8")
    for path in [
        '"/reportup"',
        '"/api/v1/reportup/config"',
        '"/api/v1/reportup/hmac-secret"',
        '"/api/v1/reportup/attestation"',
        '"/api/v1/reportup/attestations"',
        '"/api/v1/reportup/preview"',
        '"/api/v1/reportup/send-now"',
        '"/api/v1/reportup/log"',
    ]:
        assert path in src, f"router missing path {path}"


def test_router_blocks_enable_without_attestation():
    src = (REPO / "configs" / "governance-hub" / "src" / "routers" / "reportup.py").read_text(encoding="utf-8")
    # Regression guard: the 409 gate must mention attestation + snapshot_sha
    assert "attestation required" in src
    assert "snapshot_sha" in src.lower() or "snapshot_sha" in src


def test_ui_page_exists_and_has_anchors():
    page = REPO / "configs" / "governance-hub" / "src" / "pages" / "reportup.html"
    assert page.exists()
    text = page.read_text(encoding="utf-8")
    for anchor in [
        "f-parent-name", "f-parent-endpoint", "f-audit-chain",
        "btn-enable", "btn-disable", "btn-send-now",
        "a-attested-by", "a-attestation-text",
        "status-banner", "log-body",
    ]:
        assert f'id="{anchor}"' in text, f"UI missing element id={anchor}"


def test_landing_page_links_to_reportup():
    main_py = (REPO / "configs" / "governance-hub" / "src" / "main.py").read_text(encoding="utf-8")
    assert 'href="/governance/reportup"' in main_py
    assert "ReportUp" in main_py
