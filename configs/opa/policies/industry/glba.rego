# GLBA — Gramm-Leach-Bliley Act
package insidellm.industry.glba

import rego.v1

deny_reasons contains reason if {
    some msg in input.messages
    msg.role == "user"
    contains_npi(msg.content)
    not input.glba_authorized
    reason := "GLBA: Non-public personal financial information requires authorized access"
}

obligations contains ob if {
    some msg in input.messages
    msg.role == "user"
    contains_npi(msg.content)
    ob := {"type": "audit.log", "priority": 2, "params": {"event_type": "npi_access", "severity": "high", "policy": "glba"}}
}

obligations contains ob if {
    some msg in input.messages
    msg.role == "user"
    contains_npi(msg.content)
    ob := {"type": "filter.fields", "priority": 1, "params": {"fields": ["account_number", "balance", "income", "tax_id"], "action": "redact"}}
}

contains_npi(content) if {
    lower_content := lower(content)
    some pattern in ["account number", "account balance", "income", "tax return", "financial statement", "credit report", "loan application"]
    contains(lower_content, pattern)
}
