# FERPA — Family Educational Rights and Privacy Act
package insidellm.industry.ferpa

import rego.v1

deny_reasons contains reason if {
    some msg in input.messages
    msg.role == "user"
    contains_student_records(msg.content)
    not input.ferpa_authorized
    reason := "FERPA: Student education records require authorized access"
}

obligations contains ob if {
    some msg in input.messages
    msg.role == "user"
    contains_student_records(msg.content)
    ob := {"type": "audit.log", "priority": 2, "params": {"event_type": "student_record_access", "severity": "high", "policy": "ferpa"}}
}

obligations contains ob if {
    some msg in input.messages
    msg.role == "user"
    contains_student_records(msg.content)
    ob := {"type": "filter.fields", "priority": 1, "params": {"fields": ["student_id", "gpa", "grades", "disciplinary"], "action": "redact"}}
}

contains_student_records(content) if {
    lower_content := lower(content)
    some pattern in ["student record", "transcript", "grade", "enrollment", "ferpa", "education record", "student id", "gpa"]
    contains(lower_content, pattern)
}
