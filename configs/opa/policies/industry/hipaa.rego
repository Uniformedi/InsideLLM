# HIPAA — Health Insurance Portability and Accountability Act
package insidellm.industry.hipaa

import rego.v1

deny_reasons contains reason if {
    some msg in input.messages
    msg.role == "user"
    contains_phi(msg.content)
    not input.hipaa_authorized
    reason := "HIPAA: Protected Health Information detected without authorization"
}

obligations contains ob if {
    some msg in input.messages
    msg.role == "user"
    contains_phi(msg.content)
    ob := {"type": "filter.fields", "priority": 1, "params": {"fields": ["mrn", "ssn", "dob", "patient_name", "diagnosis"], "action": "redact"}}
}

obligations contains ob if {
    some msg in input.messages
    msg.role == "user"
    contains_phi(msg.content)
    ob := {"type": "audit.log", "priority": 2, "params": {"event_type": "phi_access", "severity": "high", "policy": "hipaa"}}
}

obligations contains ob if {
    input.data_classification == "restricted"
    input.break_glass == true
    ob := {"type": "audit.break_glass", "priority": 2, "params": {"reason": "emergency_phi_access", "data_classification": "restricted"}}
}

contains_phi(content) if {
    lower_content := lower(content)
    some pattern in ["patient", "mrn", "medical record", "diagnosis", "treatment plan", "prescription", "health record", "phi", "hipaa", "protected health"]
    contains(lower_content, pattern)
}
