# PCI-DSS — Payment Card Industry Data Security Standard
package insidellm.industry.pci_dss

import rego.v1

deny_reasons contains reason if {
    some msg in input.messages
    msg.role == "user"
    contains_cardholder_data(msg.content)
    reason := "PCI-DSS: Cardholder data must not be processed through AI systems"
}

obligations contains ob if {
    some msg in input.messages
    msg.role == "user"
    payment_related(msg.content)
    ob := {"type": "audit.log", "priority": 2, "params": {"event_type": "payment_processing", "severity": "medium", "policy": "pci_dss"}}
}

obligations contains ob if {
    some msg in input.messages
    msg.role == "user"
    contains_cardholder_data(msg.content)
    ob := {"type": "filter.fields", "priority": 1, "params": {"fields": ["card_number", "cvv", "expiry", "pan"], "action": "redact"}}
}

contains_cardholder_data(content) if {
    lower_content := lower(content)
    some pattern in ["card number", "credit card", "cvv", "expiration date", "cardholder", "pan ", "primary account number"]
    contains(lower_content, pattern)
}

payment_related(content) if {
    lower_content := lower(content)
    some pattern in ["payment", "transaction", "refund", "chargeback", "merchant", "acquiring", "issuing"]
    contains(lower_content, pattern)
}
