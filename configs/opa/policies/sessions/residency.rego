# =============================================================================
# Sessions — Data Residency (cross-region transfer gating)
#
# Any time a session is handed off, forked, mirrored, or push-notified into a
# different regulatory region than where it was created, this rule must
# permit it. Residency is declared per-tenant at provisioning (data_region).
# Cross-region transfers are denied unless a peer allowlist entry with a
# valid transfer mechanism (e.g. SCC_v2022) covers the direction.
#
# Inputs expected:
#   input.source.tenant_id
#   input.source.data_region
#   input.target.tenant_id
#   input.target.data_region
#   input.transfer_mechanism               — e.g. "SCC_v2022" | "adequacy" |
#                                              "derogation_consent" | null
#   input.transfer_mechanism_valid_until   — ns epoch
#   input.dpia_ref                         — string id for DPIA artifact
#   data.tenants.peers                     — Rego data doc injected at boot:
#                                            [ { src_region, dst_region,
#                                                mechanism, valid_until_ns,
#                                                dpia_ref } ]
#
# Emissions:
#   deny_reasons  — non-empty ⇒ transfer denied
#   obligations   — audit + DPIA link
# =============================================================================
package insidellm.sessions.residency

import rego.v1

# Same-region transfers are always allowed (if nothing else denies).
allow_same_region if {
    input.source.data_region == input.target.data_region
}

# Allowed cross-region if a peer allowlist entry matches and is valid.
allow_cross_region if {
    input.source.data_region != input.target.data_region
    some peer in data.tenants.peers
    peer.src_region == input.source.data_region
    peer.dst_region == input.target.data_region
    peer.mechanism == input.transfer_mechanism
    peer.valid_until_ns >= time.now_ns()
}

# ---- Deny rules -------------------------------------------------------------

deny_reasons contains reason if {
    input.source.data_region != input.target.data_region
    not input.transfer_mechanism
    reason := sprintf(
        "residency transfer denied: %s -> %s requires transfer_mechanism",
        [input.source.data_region, input.target.data_region],
    )
}

deny_reasons contains reason if {
    input.source.data_region != input.target.data_region
    input.transfer_mechanism
    not allow_cross_region
    reason := sprintf(
        "residency transfer denied: %s -> %s not in peer allowlist for mechanism '%s'",
        [input.source.data_region, input.target.data_region, input.transfer_mechanism],
    )
}

deny_reasons contains reason if {
    input.source.data_region != input.target.data_region
    input.transfer_mechanism
    not input.dpia_ref
    reason := "residency transfer denied: DPIA reference required for cross-region"
}

# ---- Obligations ------------------------------------------------------------

obligations contains obligation if {
    count(deny_reasons) == 0
    obligation := {
        "type": "audit.log",
        "priority": 1,
        "params": {
            "event_type": "session.residency_authorized",
            "severity": "info",
            "policy": "sessions.residency",
            "src_region": input.source.data_region,
            "dst_region": input.target.data_region,
            "cross_region": input.source.data_region != input.target.data_region,
            "mechanism": input.transfer_mechanism,
            "dpia_ref": input.dpia_ref,
        },
    }
}
