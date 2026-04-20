# =============================================================================
# Sessions — Retention Validity (tier-driven floors + caps)
#
# Enforces that a session's configured retention satisfies every applicable
# compliance floor and respects every applicable privacy cap. Evaluated at
# session create, at any event that tightens tier (classification change,
# manifest-override, DLP escalation), and during nightly reconciliation.
#
# Tier model (see sessions design doc):
#   T0 ephemeral      24h  / 0         — break-glass ops
#   T1 public         30d  / 0
#   T2 standard       90d  / 1y
#   T3 confidential   30d  / 3y
#   T4 consumer-fin   60d  / 7y        — FDCPA/FCRA floor
#   T5 healthcare     30d  / 6y        — HIPAA floor (state-overridable)
#   T6 fin-svcs       30d  / 7y        — SOX/GLBA/17a-4 floor, WORM cold
#   T7 high-security  7d   / 0
#
# Inputs expected:
#   input.session.tenant_id
#   input.session.security_tier
#   input.session.security_tier_source    — tenant|manifest|classification
#   input.session.retention_floor_days
#   input.session.retention_cap_days      — nullable
#   input.session.legal_hold              — bool
#   input.tenant.tier_floor               — tenant-declared floor (days)
#   input.tenant.tier_cap                 — tenant-declared cap (days, nullable)
#   input.manifest.min_security_tier      — T0..T7 (may tighten)
#   input.classification.min_security_tier — T0..T7 (may tighten)
#
# Emissions:
#   deny_reasons      — non-empty ⇒ session state MUST flip to quarantined
#   obligations       — audit + operator alert for compliance conflicts
# =============================================================================
package insidellm.sessions.retention

import rego.v1

# ---- Tier floor / cap tables ------------------------------------------------

_tier_floors := {
    "T0": 1,
    "T1": 30,
    "T2": 90,
    "T3": 30,
    "T4": 60,
    "T5": 30,
    "T6": 30,
    "T7": 7,
}

_tier_max_total := {
    "T0": 1,
    "T1": 30,
    "T2": 455,       # 1y 90d
    "T3": 1125,      # 3y 30d
    "T4": 2555,      # 7y
    "T5": 2190,      # 6y default (state overrides)
    "T6": 2555,      # 7y
    "T7": 7,
}

_tier_order := {
    "T0": 0, "T1": 1, "T2": 2, "T3": 3,
    "T4": 4, "T5": 5, "T6": 6, "T7": 7,
}

# ---- Effective tier ---------------------------------------------------------

effective_tier := t if {
    candidates := [c |
        c := input.session.security_tier
    ] ++ [c |
        c := input.manifest.min_security_tier
        c != null
    ] ++ [c |
        c := input.classification.min_security_tier
        c != null
    ]
    t := _tier_max(candidates)
}

_tier_max(xs) := top if {
    count(xs) > 0
    ranked := [[_tier_order[x], x] | some x in xs]
    sorted := sort(ranked)
    top := sorted[count(sorted) - 1][1]
}

# ---- Deny rules -------------------------------------------------------------

# Floor violation: session retention below the required minimum for its tier.
deny_reasons contains reason if {
    floor := _tier_floors[effective_tier]
    input.session.retention_floor_days < floor
    reason := sprintf(
        "retention floor %d days < tier %s required floor %d days",
        [input.session.retention_floor_days, effective_tier, floor],
    )
}

# Cap violation: retention exceeds the tier's configured cap and no legal hold.
deny_reasons contains reason if {
    cap := _tier_max_total[effective_tier]
    input.session.retention_cap_days != null
    input.session.retention_cap_days > cap
    not input.session.legal_hold
    reason := sprintf(
        "retention cap %d days > tier %s max %d days; legal hold required",
        [input.session.retention_cap_days, effective_tier, cap],
    )
}

# Internal conflict: floor > cap once all inputs are resolved.
deny_reasons contains reason if {
    floor := _tier_floors[effective_tier]
    cap := _tier_max_total[effective_tier]
    floor > cap
    not input.session.legal_hold
    reason := sprintf(
        "compliance conflict on tier %s: floor %d > cap %d (legal basis needed)",
        [effective_tier, floor, cap],
    )
}

# Tenant-level config consistency check.
deny_reasons contains reason if {
    input.tenant.tier_floor
    input.tenant.tier_floor > _tier_floors[effective_tier]
    input.session.retention_floor_days < input.tenant.tier_floor
    reason := sprintf(
        "tenant-configured floor %d days exceeds session floor %d days",
        [input.tenant.tier_floor, input.session.retention_floor_days],
    )
}

# ---- Obligations ------------------------------------------------------------

# Compliance conflict quarantine trigger.
obligations contains obligation if {
    count(deny_reasons) > 0
    obligation := {
        "type": "session.quarantine",
        "priority": 1,
        "params": {
            "session_id": input.session.session_id,
            "reason": "retention_conflict",
            "tier": effective_tier,
        },
    }
}

# Always audit the decision.
obligations contains obligation if {
    obligation := {
        "type": "audit.log",
        "priority": 2,
        "params": {
            "event_type": "session.retention_evaluated",
            "severity": "info",
            "policy": "sessions.retention",
            "effective_tier": effective_tier,
            "floor_days": _tier_floors[effective_tier],
            "cap_days": _tier_max_total[effective_tier],
            "session_id": input.session.session_id,
            "denied": count(deny_reasons) > 0,
        },
    }
}
