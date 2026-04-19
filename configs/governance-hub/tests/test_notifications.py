"""Unit tests for P2.1 notification emitter + DLP sidecar.

Covers:
  * dlp_scan: pattern detection + redaction + severity counting
  * notification_service:
    - target parsing (teams/slack/email://…)
    - DLP modes: off (passthrough), redact (mask but send), block (stop)
    - webhook URL resolution via env vars
    - fan-out via send_many
    - fail-soft on missing webhook / provider error
    - hit fingerprints returned; raw matched text never leaves the service
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.services import dlp_scan
from src.services import notification_service as ns


# ---------------------------------------------------------------------------
# DLP scan
# ---------------------------------------------------------------------------


def test_scan_detects_ssn_and_credit_card():
    text = "Customer SSN 123-45-6789 paid via 4111-1111-1111-1111 yesterday."
    hits = dlp_scan.scan_text(text)
    patterns = {h.pattern for h in hits}
    assert "ssn" in patterns or "ssn_labeled" in patterns
    assert "credit_card" in patterns


def test_scan_hit_dict_excludes_raw_match():
    """Regression guard — leaking the match defeats the point of DLP."""
    hits = dlp_scan.scan_text("SSN: 123-45-6789")
    assert hits
    for h in hits:
        d = h.to_dict()
        assert "match" not in d
        assert "sha12" in d and len(d["sha12"]) == 12


def test_scan_severity_counts():
    hits = dlp_scan.scan_text(
        "SSN 123-45-6789, DOB: 04/18/1980, contact foo@bar.com"
    )
    counts = dlp_scan.severity_counts(hits)
    assert counts["critical"] >= 1      # SSN
    assert counts["high"] >= 1          # DOB
    assert counts["low"] >= 1           # email


def test_redact_replaces_critical_and_high_by_default():
    text = "SSN 123-45-6789 for account 12345678901 DOB 04/18/1980"
    redacted, hits = dlp_scan.redact_text(text)
    assert "123-45-6789" not in redacted
    assert "[REDACTED-SSN]" in redacted or "[REDACTED" in redacted
    assert len(hits) >= 2


def test_redact_preserves_emails_by_default():
    """Emails are low-severity. Redacting them would break notification
    routing (recipient addresses appear in message bodies)."""
    text = "Hand off to alice@example.com please."
    redacted, hits = dlp_scan.redact_text(text)
    assert "alice@example.com" in redacted


def test_redact_force_patterns_targets_specific_low_severity():
    text = "Contact alice@example.com"
    redacted, hits = dlp_scan.redact_text(text, force_patterns=["email"])
    assert "alice@example.com" not in redacted
    assert "[email]" in redacted


def test_contains_critical_flags_ssn():
    hits = dlp_scan.scan_text("SSN 123-45-6789")
    assert dlp_scan.contains_critical(hits) is True


def test_empty_text_scans_clean():
    assert dlp_scan.scan_text("") == []
    assert dlp_scan.scan_text(None) == []  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Target parsing
# ---------------------------------------------------------------------------


def test_parse_target_valid_schemes():
    assert ns._parse_target("teams://default") == ("teams", "default")
    assert ns._parse_target("slack://compliance") == ("slack", "compliance")
    assert ns._parse_target("email://alice@company.com") == ("email", "alice@company.com")


@pytest.mark.parametrize("bad", ["", "teams", "https://foo", "teams://", "zzz://x"])
def test_parse_target_rejects_invalid(bad):
    with pytest.raises(ValueError):
        ns._parse_target(bad)


# ---------------------------------------------------------------------------
# Webhook resolution
# ---------------------------------------------------------------------------


def test_webhook_url_prefers_specific_channel(monkeypatch):
    monkeypatch.setenv("TEAMS_WEBHOOK_DEFAULT", "https://default")
    monkeypatch.setenv("TEAMS_WEBHOOK_COMPLIANCE", "https://specific")
    assert ns._webhook_url("teams", "compliance") == "https://specific"
    assert ns._webhook_url("teams", "default") == "https://default"


def test_webhook_url_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_DEFAULT", "https://slack-default")
    monkeypatch.delenv("SLACK_WEBHOOK_UNSET_CHANNEL", raising=False)
    assert ns._webhook_url("slack", "unset_channel") == "https://slack-default"


def test_webhook_url_returns_none_when_unconfigured(monkeypatch):
    monkeypatch.delenv("TEAMS_WEBHOOK_DEFAULT", raising=False)
    monkeypatch.delenv("TEAMS_WEBHOOK_GHOST", raising=False)
    assert ns._webhook_url("teams", "ghost") is None


# ---------------------------------------------------------------------------
# DLP middleware
# ---------------------------------------------------------------------------


def test_dlp_off_passes_text_through():
    req = ns.NotificationRequest(
        event_type="t", target="teams://x", subject="s", body="SSN 123-45-6789",
        dlp_mode="off",
    )
    subj, body, hits, blocked = ns._apply_dlp(req)
    assert body == "SSN 123-45-6789"
    # Even in `off` mode we don't run the scanner.
    assert hits == [] and blocked is False


def test_dlp_block_stops_on_critical():
    req = ns.NotificationRequest(
        event_type="t", target="teams://x", subject="s",
        body="Customer SSN 123-45-6789",
        dlp_mode="block",
    )
    _, _, hits, blocked = ns._apply_dlp(req)
    assert blocked is True
    assert any(h.severity == "critical" for h in hits)


def test_dlp_redact_masks_and_sends():
    req = ns.NotificationRequest(
        event_type="t", target="teams://x", subject="s",
        body="Customer SSN 123-45-6789 at 04/18/1980",
        dlp_mode="redact",
    )
    _, body, hits, blocked = ns._apply_dlp(req)
    assert blocked is False
    assert "123-45-6789" not in body
    assert "[REDACTED" in body
    assert len(hits) >= 1


# ---------------------------------------------------------------------------
# End-to-end send (provider mocked)
# ---------------------------------------------------------------------------


class _FakeResp:
    def __init__(self, status=200, text="ok"):
        self.status_code = status
        self.text = text

    def raise_for_status(self):
        import httpx
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("err", request=MagicMock(), response=self)


class _FakeAsyncClient:
    def __init__(self, resp=None):
        self._resp = resp or _FakeResp()
        self.calls: list[tuple[str, dict]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None):
        self.calls.append((url, json or {}))
        return self._resp


@pytest.mark.asyncio
async def test_send_teams_redacts_and_calls_webhook(monkeypatch):
    monkeypatch.setenv("TEAMS_WEBHOOK_DEFAULT", "https://teams-hook")
    fake = _FakeAsyncClient()

    with patch.object(ns, "httpx") as mhttpx:
        mhttpx.AsyncClient = MagicMock(return_value=fake)
        import httpx as _real
        mhttpx.HTTPStatusError = _real.HTTPStatusError

        result = await ns.send(ns.NotificationRequest(
            event_type="approval_pending",
            target="teams://default",
            subject="Approval",
            body="Consumer SSN 123-45-6789 needs verification",
            severity="warning",
        ))

    assert result.ok is True
    assert result.provider == "teams"
    assert result.redactions_applied >= 1
    # Webhook body must have the mask, never the raw SSN.
    posted_payload = fake.calls[0][1]
    assert "123-45-6789" not in str(posted_payload)
    assert "[REDACTED" in str(posted_payload)


@pytest.mark.asyncio
async def test_send_blocked_by_dlp_returns_blocked_result(monkeypatch):
    monkeypatch.setenv("TEAMS_WEBHOOK_DEFAULT", "https://teams-hook")
    fake = _FakeAsyncClient()

    with patch.object(ns, "httpx") as mhttpx:
        mhttpx.AsyncClient = MagicMock(return_value=fake)
        import httpx as _real
        mhttpx.HTTPStatusError = _real.HTTPStatusError

        result = await ns.send(ns.NotificationRequest(
            event_type="t", target="teams://default",
            subject="s", body="SSN 123-45-6789 leak",
            dlp_mode="block",
        ))

    assert result.ok is False
    assert result.blocked_by_dlp is True
    assert result.error and "blocked by DLP" in result.error
    # Verify the webhook was NOT called.
    assert fake.calls == []


@pytest.mark.asyncio
async def test_send_without_webhook_fails_soft(monkeypatch):
    monkeypatch.delenv("TEAMS_WEBHOOK_DEFAULT", raising=False)
    monkeypatch.delenv("TEAMS_WEBHOOK_NOHOOK", raising=False)

    result = await ns.send(ns.NotificationRequest(
        event_type="t", target="teams://nohook",
        subject="s", body="clean body with nothing sensitive",
    ))
    assert result.ok is False
    assert result.error and "webhook" in result.error.lower()


@pytest.mark.asyncio
async def test_send_invalid_target_reports_error():
    result = await ns.send(ns.NotificationRequest(
        event_type="t", target="garbage-target",
        subject="s", body="b",
    ))
    assert result.ok is False
    assert "invalid target URI" in (result.error or "")


@pytest.mark.asyncio
async def test_send_many_fans_out(monkeypatch):
    monkeypatch.setenv("TEAMS_WEBHOOK_DEFAULT", "https://teams-hook")
    monkeypatch.setenv("SLACK_WEBHOOK_DEFAULT", "https://slack-hook")
    fake = _FakeAsyncClient()

    with patch.object(ns, "httpx") as mhttpx:
        mhttpx.AsyncClient = MagicMock(return_value=fake)
        import httpx as _real
        mhttpx.HTTPStatusError = _real.HTTPStatusError

        results = await ns.send_many([
            ns.NotificationRequest(event_type="t", target="teams://default",
                                   subject="s", body="b"),
            ns.NotificationRequest(event_type="t", target="slack://default",
                                   subject="s", body="b"),
        ])

    assert len(results) == 2
    assert {r.provider for r in results} == {"teams", "slack"}
    assert all(r.ok for r in results)
