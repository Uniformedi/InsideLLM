# =============================================================================
# Humility — RAG Scope Enforcement (InsideLLM enterprise overlay, mandatory)
#
# Enforces that knowledge collections actually retrieved for a request
# are a subset of the collections declared in the agent's manifest. Without
# this, a prompt-injection attack or a compromised tool could redirect
# retrieval at an unauthorized collection (e.g. an FDCPA-bound agent pulling
# from an HR-confidential collection, or a tier_general_business agent
# fishing inside a HIPAA-regulated corpus).
#
# Inputs expected:
#   input.requested_collections          — set/array of collection ids the
#                                          retrieval layer is about to read
#   input.agent_knowledge_collections    — set/array of collection ids
#                                          declared in the manifest
#   input.knowledge_scope                — "strict" (default) | "loose"
#                                          "loose" allows unlisted collections
#                                          but still emits an audit obligation
#
# Emitted via `deny_reasons` (aggregated into humility via the
# `insidellm.humility` package the decision entry point already imports
# through base.rego's package declaration).
#
# Implements SAIVAS §4.1 (Epistemic boundary enforcement) from
# "Uniform Gnosis, Volume I" by Dan Medina.
# =============================================================================
package insidellm.humility

import rego.v1

# Treat inputs as sets for set-math, tolerating both arrays and sets.
_requested := s if s := {c | some c in input.requested_collections}
else := set()

_allowed := s if s := {c | some c in input.agent_knowledge_collections}
else := set()

# Default strict when not specified — fail-closed ergonomic.
_scope := input.knowledge_scope
_scope := "strict" if not input.knowledge_scope

# ---- Deny rules ----

# Strict scope: any collection outside the manifest list is a deny.
# Emits ONE deny reason per out-of-scope collection for operator clarity.
deny_reasons contains reason if {
    _scope == "strict"
    some c in (_requested - _allowed)
    reason := sprintf(
        "RAG scope: agent '%s' may not retrieve collection '%s' (not in manifest.knowledge.collections)",
        [input.agent_id, c],
    )
}

# Loose scope: unlisted access permitted but recorded. No deny; audit-only.
# An obligation surfaces per out-of-scope collection so reviewers see the drift.
obligations contains obligation if {
    _scope == "loose"
    some c in (_requested - _allowed)
    obligation := {
        "type": "audit.log",
        "priority": 2,
        "params": {
            "event_type": "rag_scope_drift",
            "severity": "warning",
            "policy": "humility.rag_scope",
            "agent_id": input.agent_id,
            "collection_id": c,
            "note": "Collection retrieved outside manifest scope (loose mode).",
        },
    }
}
