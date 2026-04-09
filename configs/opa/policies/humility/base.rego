# =============================================================================
# Humility — Mandatory AI Alignment Policy
# Always loaded, cannot be disabled. Highest precedence.
# Ensures AI outputs remain humble, transparent, and human-centered.
# =============================================================================
package insidellm.humility

import rego.v1

# ---- Deny rules ----

# 3.2.1: Block when metaphysical context produces directives
deny_reasons contains reason if {
    some msg in input.messages
    msg.role == "user"
    contains_directive_from_metaphysical(msg.content)
    reason := "Humility 1: Metaphysical context must not produce directives"
}

# 3.2.2: Block high-confidence output lacking uncertainty declaration
deny_reasons contains reason if {
    input.request_type == "high_impact"
    not input.uncertainty_declared
    reason := "Humility 2: High-confidence output requires explicit uncertainty declaration"
}

# 3.2.3: Block authority or superiority claims
deny_reasons contains reason if {
    some msg in input.messages
    msg.role == "user"
    claims_authority(msg.content)
    reason := "Humility 3: System must not claim authority or superiority"
}

# 3.2.5: Block high-impact output without documented human consensus
deny_reasons contains reason if {
    input.data_classification == "restricted"
    not input.has_human_consensus
    reason := "Humility 4: Restricted data requires documented human consensus"
}

# 3.2.6: Block asymmetric persuasion
deny_reasons contains reason if {
    some msg in input.messages
    msg.role == "user"
    asymmetric_persuasion(msg.content)
    reason := "Humility 5: Asymmetric persuasion patterns detected"
}

# 3.3: Epistemic constraint — block extrapolation beyond validated domains
deny_reasons contains reason if {
    input.request_type == "prediction"
    not input.within_validated_domain
    reason := "Humility 6: Extrapolation beyond validated domains is prohibited"
}

# ---- Obligations (always required) ----

obligations contains obligation if {
    obligation := {
        "type": "audit.log",
        "priority": 2,
        "params": {
            "event_type": "humility_evaluation",
            "severity": "info",
            "policy": "humility",
        },
    }
}

# Tag restricted data access
obligations contains obligation if {
    input.data_classification == "restricted"
    obligation := {
        "type": "audit.tag",
        "priority": 2,
        "params": {
            "tags": ["restricted_access", "humility_flagged"],
        },
    }
}

# Require attestation for restricted data
obligations contains obligation if {
    input.data_classification == "restricted"
    obligation := {
        "type": "require.attestation",
        "priority": 3,
        "params": {
            "action_type": "restricted_data_access",
            "attestation_text": "I acknowledge I am accessing restricted data and accept responsibility.",
        },
    }
}

# ---- Helper rules ----

contains_directive_from_metaphysical(content) if {
    lower_content := lower(content)
    some pattern in [
        "you must believe",
        "the universe demands",
        "divine purpose",
        "cosmic truth",
        "absolute moral authority",
    ]
    contains(lower_content, pattern)
}

claims_authority(content) if {
    lower_content := lower(content)
    some pattern in [
        "i am always right",
        "my answer is absolute",
        "trust me without question",
        "i have superior knowledge",
        "i know better than humans",
    ]
    contains(lower_content, pattern)
}

asymmetric_persuasion(content) if {
    lower_content := lower(content)
    some pattern in [
        "you have no choice",
        "there is only one option",
        "you must comply",
        "failure to act will",
        "this is your last chance",
    ]
    contains(lower_content, pattern)
}
