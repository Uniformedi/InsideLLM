# =============================================================================
# Sessions — Push Payload Filter (tier-aware Web Push content stripping)
#
# Web Push endpoints route through third-party intermediaries (Mozilla, Apple,
# Google autopush). Treat those endpoints as untrusted. Before handing a
# payload to the push sender, strip content to the minimum the session's tier
# permits. The enforcement layer sends `allowed_payload` verbatim; anything
# not returned is not sent.
#
# Tier policy (see PWA design doc):
#   T0 ephemeral      — no push
#   T1 public         — full content
#   T2 standard       — full content
#   T3 confidential   — metadata only (session_id, title, event_type)
#   T4 consumer-fin   — metadata + redacted preview
#   T5 healthcare     — "You have a message" (no content, no title)
#   T6 fin-svcs       — metadata only
#   T7 high-security  — no push
#
# Inputs expected:
#   input.session.security_tier
#   input.event.event_type               — e.g. session.handoff.requested
#   input.event.session_id
#   input.event.title                    — surface-native title
#   input.event.preview                  — short content snippet
#   input.event.preview_redacted         — redacted variant
#   input.subscription.allowed_tiers     — tiers this subscription may receive
#
# Emissions:
#   allowed       — bool
#   allowed_payload — the stripped object to send (empty if not allowed)
#   deny_reasons  — why the push was suppressed, for observability
# =============================================================================
package insidellm.sessions.push

import rego.v1

_no_push_tiers := {"T0", "T7"}

# ---- Allow / deny -----------------------------------------------------------

allowed if {
    not input.session.security_tier in _no_push_tiers
    input.session.security_tier in input.subscription.allowed_tiers
}

deny_reasons contains reason if {
    input.session.security_tier in _no_push_tiers
    reason := sprintf(
        "push suppressed: tier %s does not permit push notifications",
        [input.session.security_tier],
    )
}

deny_reasons contains reason if {
    not input.session.security_tier in input.subscription.allowed_tiers
    reason := sprintf(
        "push suppressed: subscription not enrolled for tier %s",
        [input.session.security_tier],
    )
}

# ---- Per-tier payload shapes ------------------------------------------------

# T1 / T2 — full content
allowed_payload := payload if {
    allowed
    input.session.security_tier in {"T1", "T2"}
    payload := {
        "event_type": input.event.event_type,
        "session_id": input.event.session_id,
        "title": input.event.title,
        "preview": input.event.preview,
    }
}

# T3 / T6 — metadata only (session_id, title, event_type)
allowed_payload := payload if {
    allowed
    input.session.security_tier in {"T3", "T6"}
    payload := {
        "event_type": input.event.event_type,
        "session_id": input.event.session_id,
        "title": input.event.title,
    }
}

# T4 — metadata + redacted preview
allowed_payload := payload if {
    allowed
    input.session.security_tier == "T4"
    payload := {
        "event_type": input.event.event_type,
        "session_id": input.event.session_id,
        "title": input.event.title,
        "preview": input.event.preview_redacted,
    }
}

# T5 — no content, no title
allowed_payload := payload if {
    allowed
    input.session.security_tier == "T5"
    payload := {
        "event_type": "session.message",
        "body": "You have a message",
    }
}

# No-push tiers or unauthorized subscription — empty object.
allowed_payload := {} if {
    not allowed
}

# ---- Obligations ------------------------------------------------------------

obligations contains obligation if {
    obligation := {
        "type": "audit.log",
        "priority": 2,
        "params": {
            "event_type": "session.push.decided",
            "severity": "info",
            "policy": "sessions.push",
            "tier": input.session.security_tier,
            "allowed": allowed,
            "deny_count": count(deny_reasons),
        },
    }
}
