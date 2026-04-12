"""
DLP Guardrail — Data Loss Prevention enforcement at the LiteLLM gateway.

Runs on every request regardless of frontend (Open WebUI, Claude Code CLI,
custom apps). Scans both inbound user messages and outbound assistant
responses for PII, PHI, credit cards, SSNs, API keys, and connection
strings.

Replaces the per-frontend DLP pipeline that previously lived in Open WebUI.
By the time a request reaches LiteLLM, any file content has already been
inlined into the messages array, so scanning here covers both message text
and uploaded file content with a single regex pass.

Configured via environment variables (see DEFAULTS below). All valves can
be overridden per-deployment without code changes.
"""

import asyncio
import json
import logging
import os
import re
from typing import Any

from litellm.integrations.custom_logger import CustomLogger

logger = logging.getLogger("litellm.dlp_guardrail")


# ============================================================================
# Detection patterns (mirrors configs/open-webui/dlp-pipeline.py v2.0.0)
# ============================================================================

PATTERNS: dict[str, dict[str, str]] = {
    "ssn": {
        "regex": r"\b\d{3}[-\u2013\u2014\s]?\d{2}[-\u2013\u2014\s]?\d{4}\b",
        "description": "Social Security Number",
        "valve": "block_ssn",
        "severity": "critical",
    },
    "ssn_labeled": {
        "regex": r"(?:social\s*security(?:\s*(?:number|no\.?|num\.?|#))?|ssn|ss\s*#|ss\s*no\.?)[\s:.=#]*\d{3}[-\u2013\u2014\s]?\d{2}[-\u2013\u2014\s]?\d{4}",
        "description": "Social Security Number (labeled)",
        "valve": "block_ssn",
        "severity": "critical",
    },
    "credit_card": {
        "regex": r"\b(?:4\d{3}|5[1-5]\d{2}|3[47]\d{2}|6(?:011|5\d{2}))[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b",
        "description": "Credit Card Number",
        "valve": "block_credit_cards",
        "severity": "critical",
    },
    "credit_card_generic": {
        "regex": r"\b(?:\d{4}[-\s]){3}\d{4}\b",
        "description": "Potential Credit Card Number",
        "valve": "block_credit_cards",
        "severity": "high",
    },
    "phi_mrn": {
        "regex": r"\b(?:MRN|Medical Record|Patient ID)[\s:#]*\d{5,}\b",
        "description": "Medical Record Number",
        "valve": "block_phi",
        "severity": "critical",
    },
    "phi_dob": {
        "regex": r"\b(?:DOB|D\.O\.B\.?|date\s+of\s+birth|birth\s*date|birth\s*day|b[\-\s]?day|born(?:\s+on)?|fecha\s+de\s+nacimiento)[\s:]*\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}\b",
        "description": "Date of Birth (labeled)",
        "valve": "block_phi",
        "severity": "high",
    },
    "phi_dob_iso": {
        "regex": r"\b(?:DOB|D\.O\.B\.?|date\s+of\s+birth|birth\s*date|birth\s*day|b[\-\s]?day|born(?:\s+on)?)[\s:]*\d{4}[/\-\.]\d{1,2}[/\-\.]\d{1,2}\b",
        "description": "Date of Birth - ISO format",
        "valve": "block_phi",
        "severity": "high",
    },
    "phi_dob_text_month": {
        "regex": r"\b(?:DOB|D\.O\.B\.?|date\s+of\s+birth|birth\s*date|birth\s*day|b[\-\s]?day|born(?:\s+on)?)[\s:]*(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?\s+\d{1,2},?\s+\d{2,4}",
        "description": "Date of Birth - text month",
        "valve": "block_phi",
        "severity": "high",
    },
    "phi_dob_standalone": {
        "regex": r"\b(?:0?[1-9]|1[0-2])[/\-](?:0?[1-9]|[12]\d|3[01])[/\-](?:19|20)\d{2}\b",
        "description": "Date Pattern (MM/DD/YYYY)",
        "valve": "block_standalone_dates",
        "severity": "medium",
    },
    "phi_dob_standalone_iso": {
        "regex": r"\b(?:19|20)\d{2}[/\-](?:0?[1-9]|1[0-2])[/\-](?:0?[1-9]|[12]\d|3[01])\b",
        "description": "Date Pattern (YYYY-MM-DD)",
        "valve": "block_standalone_dates",
        "severity": "medium",
    },
    "phi_diagnosis": {
        "regex": r"\b(?:ICD[-\s]?(?:9|10)[-\s]?(?:CM|PCS)?[\s:#]*[A-Z]\d{2}(?:\.\d{1,4})?)\b",
        "description": "ICD Diagnosis Code",
        "valve": "block_phi",
        "severity": "medium",
    },
    "api_key": {
        "regex": r"\b(?:sk-[a-zA-Z0-9]{20,}|api[_\-]?key[\s=:]+[\"']?[a-zA-Z0-9_\-]{16,})",
        "description": "API Key",
        "valve": "block_credentials",
        "severity": "critical",
    },
    "password_inline": {
        "regex": r"(?:password|passwd|pwd)[\s]*[=:]+[\s]*[\"']?[^\s\"']{8,}",
        "description": "Inline Password",
        "valve": "block_credentials",
        "severity": "critical",
    },
    "connection_string": {
        "regex": r"(?:Server|Data Source|Host|Provider)=[^;\n]+;(?:.*?(?:Password|Pwd|User ID)=[^;\n]+)",
        "description": "Database Connection String",
        "valve": "block_credentials",
        "severity": "critical",
    },
    "aws_key": {
        "regex": r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b",
        "description": "AWS Access Key",
        "valve": "block_credentials",
        "severity": "critical",
    },
    "private_key": {
        "regex": r"-----BEGIN (?:RSA |EC |DSA )?PRIVATE KEY-----",
        "description": "Private Key",
        "valve": "block_credentials",
        "severity": "critical",
    },
    "bank_routing": {
        "regex": r"\b(?:routing|ABA)[\s#:]*\d{9}\b",
        "description": "Bank Routing Number",
        "valve": "block_bank_accounts",
        "severity": "critical",
    },
    "bank_account": {
        "regex": r"\b(?:account|acct)[\s#:]*\d{8,17}\b",
        "description": "Bank Account Number",
        "valve": "block_bank_accounts",
        "severity": "critical",
    },
}


def _env_bool(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _load_custom_patterns() -> dict[str, dict[str, str]]:
    """Parse DLP_CUSTOM_PATTERNS env var (JSON object: {name: regex})."""
    raw = os.environ.get("DLP_CUSTOM_PATTERNS", "").strip()
    if not raw:
        return {}
    try:
        custom = json.loads(raw)
        if not isinstance(custom, dict):
            return {}
        return {
            f"custom_{name}": {
                "regex": regex,
                "description": f"Custom: {name}",
                "valve": "enabled",
                "severity": "high",
            }
            for name, regex in custom.items()
            if isinstance(regex, str)
        }
    except (json.JSONDecodeError, TypeError) as exc:
        logger.warning(f"DLP: invalid DLP_CUSTOM_PATTERNS JSON: {exc}")
        return {}


def _extract_text(content: Any) -> str:
    """Flatten message content (string or list of content blocks) to text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", ""))
        return " ".join(parts)
    return ""


def _log_to_hub_sync(hub_url: str, event_type: str, details: dict) -> None:
    """Fire-and-forget audit log to the governance hub."""
    try:
        import requests
        requests.post(
            f"{hub_url}/api/v1/obligations/audit-log",
            json={
                "event_type": event_type,
                "severity": details.get("severity", "warning"),
                "details": details,
            },
            timeout=2,
        )
    except Exception as exc:
        logger.debug(f"Could not log to governance hub ({event_type}): {exc}")


class DLPGuardrailCallback(CustomLogger):
    """LiteLLM callback that enforces DLP scanning on requests and responses.

    Modes:
        block   - reject the request with a user-friendly error
        redact  - replace matches with [REDACTED-TYPE] placeholders and proceed

    Configuration is read once at startup from environment variables. To
    change valves at runtime, restart the LiteLLM container.
    """

    def __init__(self) -> None:
        super().__init__()
        self.enabled = _env_bool("DLP_ENABLED", True)
        self.mode = os.environ.get("DLP_MODE", "block").strip().lower()
        if self.mode not in ("block", "redact"):
            logger.warning(f"DLP: unknown DLP_MODE '{self.mode}', defaulting to 'block'")
            self.mode = "block"

        # Per-category valves
        self.valves = {
            "block_ssn": _env_bool("DLP_BLOCK_SSN", True),
            "block_credit_cards": _env_bool("DLP_BLOCK_CREDIT_CARDS", True),
            "block_phi": _env_bool("DLP_BLOCK_PHI", True),
            "block_credentials": _env_bool("DLP_BLOCK_CREDENTIALS", True),
            "block_bank_accounts": _env_bool("DLP_BLOCK_BANK_ACCOUNTS", True),
            "block_standalone_dates": _env_bool("DLP_BLOCK_STANDALONE_DATES", True),
            "scan_responses": _env_bool("DLP_SCAN_RESPONSES", True),
            "log_detections": _env_bool("DLP_LOG_DETECTIONS", True),
            "enabled": True,
        }

        self.governance_hub_url = os.environ.get(
            "GOVERNANCE_HUB_URL", "http://governance-hub:8090"
        )

        # Pre-compile active patterns (significant perf win on hot path)
        all_patterns = {**PATTERNS, **_load_custom_patterns()}
        self._compiled: dict[str, dict[str, Any]] = {}
        for name, spec in all_patterns.items():
            if not self.valves.get(spec.get("valve", ""), True):
                continue
            try:
                self._compiled[name] = {
                    "pattern": re.compile(spec["regex"], re.IGNORECASE),
                    "description": spec["description"],
                    "severity": spec["severity"],
                }
            except re.error as exc:
                logger.warning(f"DLP: invalid regex for '{name}', skipping: {exc}")

        logger.info(
            f"DLPGuardrailCallback initialized "
            f"(enabled={self.enabled}, mode={self.mode}, "
            f"active_patterns={len(self._compiled)})"
        )

    # ------------------------------------------------------------------
    # Scanning helpers
    # ------------------------------------------------------------------

    def _scan(self, text: str) -> list[tuple[str, str, str]]:
        """Return [(name, description, severity)] for every pattern that hits."""
        if not text:
            return []
        return [
            (name, spec["description"], spec["severity"])
            for name, spec in self._compiled.items()
            if spec["pattern"].search(text)
        ]

    def _redact(self, text: str) -> str:
        """Replace every match with [REDACTED-TYPE]."""
        for name, spec in self._compiled.items():
            text = spec["pattern"].sub(f"[REDACTED-{name.upper()}]", text)
        return text

    def _redact_message_content(self, content: Any) -> Any:
        """Redact a message's content, preserving its shape (string or list)."""
        if isinstance(content, str):
            return self._redact(content)
        if isinstance(content, list):
            return [
                {**item, "text": self._redact(item.get("text", ""))}
                if isinstance(item, dict) and item.get("type") == "text"
                else item
                for item in content
            ]
        return content

    # ------------------------------------------------------------------
    # LiteLLM hooks
    # ------------------------------------------------------------------

    async def async_pre_call_hook(
        self, user_api_key_dict, cache, data, call_type
    ):
        """Scan inbound user messages before the LLM call."""
        if not self.enabled or call_type not in ("completion", "acompletion"):
            return data

        messages = data.get("messages", [])
        if not messages:
            return data

        # Idempotency: skip if already scanned (e.g. retry)
        metadata = data.get("metadata", {})
        if metadata.get("dlp_guardrail_evaluated"):
            return data

        user_info = user_api_key_dict or {}
        user_id = user_info.get("user", "unknown")

        # Collect detections across all user messages
        detections: list[tuple[str, str, str]] = []
        for msg in messages:
            if msg.get("role") != "user":
                continue
            text = _extract_text(msg.get("content", ""))
            detections.extend(self._scan(text))

        if not detections:
            return {**data, "metadata": {**metadata, "dlp_guardrail_evaluated": True}}

        # Audit
        if self.valves["log_detections"]:
            summary = ", ".join(sorted({f"{d[1]} ({d[2]})" for d in detections}))
            logger.warning(f"DLP: detections from user={user_id}: {summary}")

        loop = asyncio.get_event_loop()
        loop.run_in_executor(
            None,
            _log_to_hub_sync,
            self.governance_hub_url,
            "dlp_detection",
            {
                "user": user_id,
                "mode": self.mode,
                "types": sorted({d[1] for d in detections}),
                "severity": "critical"
                if any(d[2] == "critical" for d in detections)
                else "warning",
            },
        )

        # --- BLOCK mode: reject the request ---
        if self.mode == "block":
            types_found = ", ".join(sorted({d[1] for d in detections}))
            raise Exception(
                "**DLP Filter Blocked This Message**\n\n"
                f"Your message contains sensitive information ({types_found}).\n\n"
                "For security and compliance, this request was blocked before "
                "reaching the AI service. Please remove the sensitive data and "
                "try again."
            )

        # --- REDACT mode: rewrite messages and proceed ---
        new_messages = [
            {**msg, "content": self._redact_message_content(msg.get("content", ""))}
            if msg.get("role") == "user"
            else msg
            for msg in messages
        ]
        return {
            **data,
            "messages": new_messages,
            "metadata": {**metadata, "dlp_guardrail_evaluated": True},
        }

    async def async_post_call_success_hook(
        self, data, user_api_key_dict, response
    ):
        """Scan the assistant's response and redact echoed sensitive data."""
        if not self.enabled or not self.valves["scan_responses"]:
            return response

        try:
            choices = getattr(response, "choices", None) or response.get("choices", [])
        except Exception:
            return response

        if not choices:
            return response

        for choice in choices:
            message = (
                getattr(choice, "message", None)
                or (choice.get("message") if isinstance(choice, dict) else None)
            )
            if not message:
                continue

            content = (
                getattr(message, "content", None)
                if not isinstance(message, dict)
                else message.get("content")
            )
            if not isinstance(content, str) or not content:
                continue

            detections = self._scan(content)
            if not detections:
                continue

            redacted = self._redact(content)
            if isinstance(message, dict):
                message["content"] = redacted
            else:
                try:
                    message.content = redacted
                except Exception:
                    pass

            if self.valves["log_detections"]:
                logger.warning(
                    "DLP: redacted sensitive data echoed in assistant response "
                    f"({len(detections)} pattern(s))"
                )

        return response
