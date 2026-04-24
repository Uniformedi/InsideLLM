"""DLP sidecar scanner for P2.1 notifications (+ reusable elsewhere).

The regex pattern set mirrors configs/litellm/callbacks/dlp_guardrail.py so
the same things get flagged at the LiteLLM gateway AND in outbound
notifications. Kept as a standalone module so the notification path
doesn't have to import LiteLLM.

Two entry points:
  * scan_text(text) -> list[DLPHit]         — detect only
  * redact_text(text) -> (redacted, hits)   — detect + replace in place

Hit severity is one of critical / high / medium. Callers decide the
policy — for notifications we default to redact + warn-on-critical so a
mangled message still goes out but operators see a flag.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Iterable

logger = logging.getLogger("governance-hub.dlp")


# ---------------------------------------------------------------------------
# Pattern set — same shape as dlp_guardrail.py (source of truth)
# ---------------------------------------------------------------------------

# IMPORTANT: The `regex` + key names below MUST stay in sync with
# `configs/litellm/callbacks/dlp_guardrail.py::PATTERNS`. The
# `scripts/check-dlp-pattern-sync.py` drift check (and the paired
# pytest test) fail if they diverge. Gov-hub may add *extra* keys
# (e.g. `email` — not appropriate to block on LLM calls but useful to
# flag on outbound notifications); shared keys must match verbatim.
PATTERNS: dict[str, dict[str, object]] = {
    # ---- Mirrored from dlp_guardrail.py ----------------------------------
    "ssn": {
        "regex": r"\b\d{3}[-\u2013\u2014\s]?\d{2}[-\u2013\u2014\s]?\d{4}\b",
        "description": "Social Security Number",
        "severity": "critical",
        "mask": "[REDACTED-SSN]",
    },
    "ssn_labeled": {
        "regex": r"(?:social\s*security(?:\s*(?:number|no\.?|num\.?|#))?|ssn|ss\s*#|ss\s*no\.?)[\s:.=#]*\d{3}[-\u2013\u2014\s]?\d{2}[-\u2013\u2014\s]?\d{4}",
        "description": "Social Security Number (labeled)",
        "severity": "critical",
        "mask": "[REDACTED-SSN]",
    },
    "credit_card": {
        "regex": r"\b(?:4\d{3}|5[1-5]\d{2}|3[47]\d{2}|6(?:011|5\d{2}))[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b",
        "description": "Credit Card Number",
        "severity": "critical",
        "mask": "[REDACTED-CC]",
    },
    "credit_card_generic": {
        "regex": r"\b(?:\d{4}[-\s]){3}\d{4}\b",
        "description": "Potential Credit Card Number",
        "severity": "high",
        "mask": "[REDACTED-CC]",
    },
    "phi_mrn": {
        "regex": r"\b(?:MRN|Medical Record|Patient ID)[\s:#]*\d{5,}\b",
        "description": "Medical Record Number",
        "severity": "critical",
        "mask": "[REDACTED-MRN]",
    },
    "phi_dob": {
        "regex": r"\b(?:DOB|D\.O\.B\.?|date\s+of\s+birth|birth\s*date|birth\s*day|b[\-\s]?day|born(?:\s+on)?|fecha\s+de\s+nacimiento)[\s:]*\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}\b",
        "description": "Date of Birth (labeled)",
        "severity": "high",
        "mask": "[REDACTED-DOB]",
    },
    "phi_dob_iso": {
        "regex": r"\b(?:DOB|D\.O\.B\.?|date\s+of\s+birth|birth\s*date|birth\s*day|b[\-\s]?day|born(?:\s+on)?)[\s:]*\d{4}[/\-\.]\d{1,2}[/\-\.]\d{1,2}\b",
        "description": "Date of Birth - ISO format",
        "severity": "high",
        "mask": "[REDACTED-DOB]",
    },
    "phi_dob_text_month": {
        "regex": r"\b(?:DOB|D\.O\.B\.?|date\s+of\s+birth|birth\s*date|birth\s*day|b[\-\s]?day|born(?:\s+on)?)[\s:]*(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?\s+\d{1,2},?\s+\d{2,4}",
        "description": "Date of Birth - text month",
        "severity": "high",
        "mask": "[REDACTED-DOB]",
    },
    "phi_dob_standalone": {
        "regex": r"\b(?:0?[1-9]|1[0-2])[/\-](?:0?[1-9]|[12]\d|3[01])[/\-](?:19|20)\d{2}\b",
        "description": "Date Pattern (MM/DD/YYYY)",
        "severity": "medium",
        "mask": "[REDACTED-DATE]",
    },
    "phi_dob_standalone_iso": {
        "regex": r"\b(?:19|20)\d{2}[/\-](?:0?[1-9]|1[0-2])[/\-](?:0?[1-9]|[12]\d|3[01])\b",
        "description": "Date Pattern (YYYY-MM-DD)",
        "severity": "medium",
        "mask": "[REDACTED-DATE]",
    },
    "phi_diagnosis": {
        "regex": r"\b(?:ICD[-\s]?(?:9|10)[-\s]?(?:CM|PCS)?[\s:#]*[A-Z]\d{2}(?:\.\d{1,4})?)\b",
        "description": "ICD Diagnosis Code",
        "severity": "medium",
        "mask": "[REDACTED-ICD]",
    },
    "api_key": {
        "regex": r"\b(?:sk-[a-zA-Z0-9]{20,}|api[_\-]?key[\s=:]+[\"']?[a-zA-Z0-9_\-]{16,})",
        "description": "API Key",
        "severity": "critical",
        "mask": "[REDACTED-API-KEY]",
    },
    "password_inline": {
        "regex": r"(?:password|passwd|pwd)[\s]*[=:]+[\s]*[\"']?[^\s\"']{8,}",
        "description": "Inline Password",
        "severity": "critical",
        "mask": "[REDACTED-PASSWORD]",
    },
    "connection_string": {
        "regex": r"(?:Server|Data Source|Host|Provider)=[^;\n]+;(?:.*?(?:Password|Pwd|User ID)=[^;\n]+)",
        "description": "Database Connection String",
        "severity": "critical",
        "mask": "[REDACTED-CONN]",
    },
    "aws_key": {
        "regex": r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b",
        "description": "AWS Access Key",
        "severity": "critical",
        "mask": "[REDACTED-AWS]",
    },
    "private_key": {
        "regex": r"-----BEGIN (?:RSA |EC |DSA )?PRIVATE KEY-----",
        "description": "Private Key",
        "severity": "critical",
        "mask": "[REDACTED-KEY]",
    },
    "bank_routing": {
        "regex": r"\b(?:routing|ABA)[\s#:]*\d{9}\b",
        "description": "Bank Routing Number",
        "severity": "critical",
        "mask": "[REDACTED-ROUTING]",
    },
    "bank_account": {
        "regex": r"\b(?:account|acct)[\s#:]*\d{8,17}\b",
        "description": "Bank Account Number",
        "severity": "critical",
        "mask": "[REDACTED-ACCT]",
    },
    "us_street_address": {
        "regex": r"\b\d{1,6}\s+(?:[A-Z][a-zA-Z]*\s+){0,4}(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Drive|Dr|Lane|Ln|Court|Ct|Place|Pl|Square|Sq|Parkway|Pkwy|Circle|Cir|Way|Terrace|Ter|Trail|Trl|Highway|Hwy|Route|Rte)\b\.?(?:\s+(?:Apt|Apartment|Suite|Ste|Unit|#)\s*[\w-]+)?",
        "description": "US Street Address",
        "severity": "high",
        "mask": "[REDACTED-ADDRESS]",
    },
    "us_zip_labeled": {
        "regex": r"\b(?:zip|zipcode|postal\s*code)[\s:#]*\d{5}(?:-\d{4})?\b",
        "description": "US Zip Code (labeled)",
        "severity": "medium",
        "mask": "[REDACTED-ZIP]",
    },
    "phone_us": {
        "regex": r"\b(?:\+?1[-.\s]?)?\(?[2-9]\d{2}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b",
        "description": "US Phone Number",
        "severity": "high",
        "mask": "[REDACTED-PHONE]",
    },

    # ---- Gov-hub-only additions (not applicable to LLM-request blocking) -
    "email": {
        # Notifications routinely contain emails (recipient address, Teams
        # mentions); treat as a LOW-severity hit but DON'T redact by
        # default — would break routing. Callers that want aggressive
        # redaction can request it explicitly via force_patterns=['email'].
        "regex": r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b",
        "description": "Email Address",
        "severity": "low",
        "mask": "[email]",
        "redact_default": False,
    },
}


# Compiled at import time — regex compilation is not free, and notification
# dispatch happens on the hot path.
_COMPILED: dict[str, tuple[re.Pattern, dict]] = {
    name: (re.compile(meta["regex"], re.IGNORECASE), meta)
    for name, meta in PATTERNS.items()
}


# ---------------------------------------------------------------------------
# Hit type
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DLPHit:
    pattern: str            # pattern key name (ssn, credit_card, …)
    description: str        # human-readable
    severity: str           # critical | high | medium | low
    match: str              # substring that matched
    start: int
    end: int

    def to_dict(self) -> dict:
        return {
            "pattern": self.pattern,
            "description": self.description,
            "severity": self.severity,
            # Intentionally do NOT return `match` — the whole point of
            # detection is to keep the matched text from leaving. Expose
            # a fingerprint instead so audit callers can correlate.
            "length": self.end - self.start,
            "sha12": _short_hash(self.match),
        }


def _short_hash(s: str) -> str:
    import hashlib
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def scan_text(text: str, *, patterns: Iterable[str] | None = None) -> list[DLPHit]:
    """Find every DLP hit in `text`. Returns empty list for empty input."""
    if not text:
        return []
    use = list(patterns) if patterns else list(_COMPILED.keys())
    hits: list[DLPHit] = []
    for name in use:
        compiled_meta = _COMPILED.get(name)
        if compiled_meta is None:
            continue
        rx, meta = compiled_meta
        for m in rx.finditer(text):
            hits.append(DLPHit(
                pattern=name,
                description=str(meta["description"]),
                severity=str(meta["severity"]),
                match=m.group(0),
                start=m.start(),
                end=m.end(),
            ))
    return hits


def redact_text(
    text: str,
    *,
    include_low: bool = False,
    force_patterns: Iterable[str] | None = None,
) -> tuple[str, list[DLPHit]]:
    """Apply replacements. By default, low-severity hits (email) are NOT
    redacted because they'd break notification routing. Force specific
    patterns via `force_patterns`."""
    hits = scan_text(text)
    if not hits:
        return text, []

    force = set(force_patterns or [])
    # Sort hits by start position descending so index math doesn't shift.
    applied: list[DLPHit] = []
    out = text
    for h in sorted(hits, key=lambda x: -x.start):
        meta = PATTERNS[h.pattern]
        default_redact = bool(meta.get("redact_default", True))
        if not include_low and h.severity == "low" and h.pattern not in force:
            continue
        if not default_redact and h.pattern not in force:
            continue
        mask = str(meta.get("mask", "[REDACTED]"))
        out = out[:h.start] + mask + out[h.end:]
        applied.append(h)
    return out, applied


def contains_critical(hits: list[DLPHit]) -> bool:
    return any(h.severity == "critical" for h in hits)


def severity_counts(hits: list[DLPHit]) -> dict[str, int]:
    out = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for h in hits:
        out[h.severity] = out.get(h.severity, 0) + 1
    return out
