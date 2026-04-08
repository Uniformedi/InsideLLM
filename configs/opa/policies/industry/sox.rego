# SOX — Sarbanes-Oxley Act
package insidellm.industry.sox

import rego.v1

deny_reasons contains reason if {
    some msg in input.messages
    msg.role == "user"
    financial_reporting(msg.content)
    not input.sox_authorized
    reason := "SOX: Financial reporting content requires authorized access"
}

obligations contains ob if {
    some msg in input.messages
    msg.role == "user"
    financial_reporting(msg.content)
    ob := {"type": "audit.log", "priority": 2, "params": {"event_type": "financial_reporting", "severity": "high", "policy": "sox"}}
}

obligations contains ob if {
    some msg in input.messages
    msg.role == "user"
    financial_reporting(msg.content)
    ob := {"type": "require.attestation", "priority": 3, "params": {"action_type": "financial_data_access", "attestation_text": "I attest this use is authorized under SOX internal controls."}}
}

financial_reporting(content) if {
    lower_content := lower(content)
    some pattern in ["financial statement", "earnings report", "revenue recognition", "audit finding", "internal control", "material weakness", "restatement"]
    contains(lower_content, pattern)
}
