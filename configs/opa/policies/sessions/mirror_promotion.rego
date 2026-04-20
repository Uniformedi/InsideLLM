# =============================================================================
# Sessions — Mirror Promotion (promote a non-primary surface binding)
#
# Promoting a mirror changes the authoritative surface for a canonical session.
# That is an authority transfer, so this rule enforces tier-graded controls:
# separation of duties, step-up auth, out-of-band approval surface, and
# role-eligibility derived from NIST 800-53 AC-5/AC-6, SOC 2 CC6, HIPAA
# §164.312, GLBA, SOX ITGC, SEC 17a-4, FDCPA/FCRA, and GDPR Art. 32.
#
# Inputs expected:
#   input.session.session_id
#   input.session.security_tier
#   input.session.tenant_id
#   input.request.requester.sub
#   input.request.requester.surface         — surface the request came from
#   input.request.promoted_surface          — surface being promoted to primary
#   input.request.approvers                 — list of { sub, surface, auth_method,
#                                                       roles[], ticket_ref? }
#   input.request.reason                    — required, written
#   input.request.idempotency_key           — uuid
#   input.request.timestamp_ns
#
# Tier control matrix (see sessions design doc):
#   T0/T1        self-approve (requester only); TOTP / password re-prompt
#   T2           owner OR delegated manager; TOTP
#   T3           2-party, SoD, WebAuthn approver, out-of-band surface, 15min
#   T4           2-party, ≥1 compliance role; WebAuthn both; OOB; 10min
#   T5           2-party, ≥1 Privacy Officer (or delegate); WebAuthn + PHI attest
#   T6           3-party: requester + approver + compliance; ticket id; WebAuthn;
#                approvers on two distinct OOB surfaces; 5min
#   T7           disabled; tenant-admin break-glass only
# =============================================================================
package insidellm.sessions.mirror

import rego.v1

# ---- Tunables --------------------------------------------------------------

_approval_window_seconds := {
    "T3": 900,
    "T4": 600,
    "T5": 600,
    "T6": 300,
}

_required_approver_count := {
    "T0": 0,
    "T1": 0,
    "T2": 0,
    "T3": 1,
    "T4": 1,
    "T5": 1,
    "T6": 2,
}

_required_role_any_approver := {
    "T4": {"compliance"},
    "T5": {"privacy-officer"},
    "T6": {"compliance"},
}

# ---- Universal invariants --------------------------------------------------

# Reason is always required for T2+.
deny_reasons contains "mirror promotion denied: reason required" if {
    input.session.security_tier != "T0"
    input.session.security_tier != "T1"
    not input.request.reason
}

# SoD: no approver may equal the requester.
deny_reasons contains reason if {
    some a in input.request.approvers
    a.sub == input.request.requester.sub
    reason := "mirror promotion denied: approver cannot equal requester (SoD violation)"
}

# Idempotency key required (replay protection).
deny_reasons contains "mirror promotion denied: idempotency_key required" if {
    not input.request.idempotency_key
}

# T7 is disabled entirely — break-glass is handled outside this rule.
deny_reasons contains reason if {
    input.session.security_tier == "T7"
    reason := "mirror promotion denied: tier T7 disallows promotion (break-glass only)"
}

# Approval count must meet the tier's minimum.
deny_reasons contains reason if {
    needed := _required_approver_count[input.session.security_tier]
    count(input.request.approvers) < needed
    reason := sprintf(
        "mirror promotion denied: tier %s requires %d approver(s), got %d",
        [input.session.security_tier, needed, count(input.request.approvers)],
    )
}

# ---- Out-of-band surface enforcement (T3+) ---------------------------------

# Every approver must approve from a surface OTHER than the one being promoted.
deny_reasons contains reason if {
    input.session.security_tier in {"T3", "T4", "T5", "T6"}
    some a in input.request.approvers
    a.surface == input.request.promoted_surface
    reason := sprintf(
        "mirror promotion denied: approver '%s' must use an out-of-band surface",
        [a.sub],
    )
}

# T6 requires approvers on two *distinct* OOB surfaces.
deny_reasons contains reason if {
    input.session.security_tier == "T6"
    surfaces := {a.surface | some a in input.request.approvers}
    count(surfaces) < 2
    reason := "mirror promotion denied: tier T6 requires approvers on two distinct surfaces"
}

# ---- Authentication strength (step-up) -------------------------------------

# T3+: every approver must use WebAuthn.
deny_reasons contains reason if {
    input.session.security_tier in {"T3", "T4", "T5", "T6"}
    some a in input.request.approvers
    a.auth_method != "webauthn"
    reason := sprintf(
        "mirror promotion denied: approver '%s' used %s; tier %s requires webauthn",
        [a.sub, a.auth_method, input.session.security_tier],
    )
}

# T6: requester must also have WebAuthn'd.
deny_reasons contains reason if {
    input.session.security_tier == "T6"
    input.request.requester.auth_method != "webauthn"
    reason := "mirror promotion denied: tier T6 requires requester to authenticate via webauthn"
}

# ---- Role eligibility -------------------------------------------------------

# T4/T5/T6: at least one approver must carry the required role.
deny_reasons contains reason if {
    required := _required_role_any_approver[input.session.security_tier]
    not _some_approver_has_any(required)
    reason := sprintf(
        "mirror promotion denied: tier %s requires at least one approver with role in %v",
        [input.session.security_tier, required],
    )
}

# T6: a ticket reference is mandatory on at least one approver.
deny_reasons contains reason if {
    input.session.security_tier == "T6"
    not _some_approver_has_ticket
    reason := "mirror promotion denied: tier T6 requires a ticket reference"
}

# ---- Obligations ------------------------------------------------------------

# Record the promotion decision on the hash chain.
obligations contains obligation if {
    obligation := {
        "type": "audit.log",
        "priority": 1,
        "params": {
            "event_type": "session.mirror.promotion_decided",
            "severity": "info",
            "policy": "sessions.mirror",
            "session_id": input.session.session_id,
            "tier": input.session.security_tier,
            "approver_count": count(input.request.approvers),
            "denied": count(deny_reasons) > 0,
            "reason": input.request.reason,
        },
    }
}

# Tier-specific compliance artifacts.
obligations contains obligation if {
    count(deny_reasons) == 0
    input.session.security_tier == "T4"
    obligation := {
        "type": "compliance.fdcpa_access_log",
        "priority": 1,
        "params": {"session_id": input.session.session_id},
    }
}

obligations contains obligation if {
    count(deny_reasons) == 0
    input.session.security_tier == "T5"
    obligation := {
        "type": "compliance.hipaa_access_log",
        "priority": 1,
        "params": {"session_id": input.session.session_id},
    }
}

obligations contains obligation if {
    count(deny_reasons) == 0
    input.session.security_tier == "T6"
    obligation := {
        "type": "compliance.sox_17a4_change_record",
        "priority": 1,
        "params": {
            "session_id": input.session.session_id,
            "ticket_ref": _first_ticket,
        },
    }
}

# Revoke the old primary's session token after a successful promotion.
obligations contains obligation if {
    count(deny_reasons) == 0
    obligation := {
        "type": "token.revoke",
        "priority": 1,
        "params": {
            "scope": "session",
            "session_id": input.session.session_id,
            "surface": input.request.source_surface,
        },
    }
}

# ---- Helpers ----------------------------------------------------------------

_some_approver_has_any(required_roles) if {
    some a in input.request.approvers
    some r in a.roles
    r in required_roles
}

_some_approver_has_ticket if {
    some a in input.request.approvers
    a.ticket_ref
    a.ticket_ref != ""
}

_first_ticket := t if {
    some a in input.request.approvers
    a.ticket_ref
    t := a.ticket_ref
}
