# FDCPA — Fair Debt Collection Practices Act
package insidellm.industry.fdcpa

import rego.v1

deny_reasons contains reason if {
    some msg in input.messages
    msg.role == "user"
    generates_collection_communication(msg.content)
    not input.fdcpa_compliant_template
    reason := "FDCPA: Collection communications must use compliant templates"
}

obligations contains ob if {
    some msg in input.messages
    msg.role == "user"
    debt_related(msg.content)
    ob := {"type": "audit.log", "priority": 2, "params": {"event_type": "debt_communication", "severity": "high", "policy": "fdcpa"}}
}

obligations contains ob if {
    some msg in input.messages
    msg.role == "user"
    debt_related(msg.content)
    ob := {"type": "audit.tag", "priority": 2, "params": {"tags": ["fdcpa_regulated", "tier1_decision"]}}
}

obligations contains ob if {
    some msg in input.messages
    msg.role == "user"
    generates_collection_communication(msg.content)
    ob := {"type": "review.queue", "priority": 4, "params": {"review_type": "collection_communication", "regulation": "fdcpa"}}
}

generates_collection_communication(content) if {
    lower_content := lower(content)
    some pattern in ["write a collection letter", "draft a demand", "create a notice of debt", "generate a payment reminder"]
    contains(lower_content, pattern)
}

debt_related(content) if {
    lower_content := lower(content)
    some pattern in ["debt", "collection", "delinquent", "past due", "garnishment", "settlement offer", "payment plan", "debtor"]
    contains(lower_content, pattern)
}
