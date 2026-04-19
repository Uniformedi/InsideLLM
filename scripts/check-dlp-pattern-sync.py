#!/usr/bin/env python3
"""Fail-loud drift check between the two DLP pattern tables.

`configs/litellm/callbacks/dlp_guardrail.py`
    Runs on every LiteLLM request; PATTERNS is the authoritative source.

`configs/governance-hub/src/services/dlp_scan.py`
    Mirror used by the P2.1 notification sidecar (and anything else in
    the gov-hub container that can't import LiteLLM). Copies PATTERNS
    verbatim by key + regex.

The gov-hub side may *add* patterns the LiteLLM side doesn't need (e.g.
email, which LiteLLM must not block — emails legitimately appear in
prompts — but which we still want to flag in outbound chat bodies).
Shared keys MUST have identical regex strings.

Usage:
  python scripts/check-dlp-pattern-sync.py            # exit 0/non-zero
  python scripts/check-dlp-pattern-sync.py --verbose  # list every key
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

LITELLM_PATH = REPO / "configs" / "litellm" / "callbacks" / "dlp_guardrail.py"
GOVHUB_PATH = REPO / "configs" / "governance-hub" / "src" / "services" / "dlp_scan.py"


def _extract_patterns(path: Path) -> dict[str, str]:
    """Parse `PATTERNS = {...}` and return {name: regex_string}.

    Raises if the file doesn't define a top-level PATTERNS dict whose
    values are dicts containing a `regex` key — the shape both modules
    commit to.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        # Accept both `PATTERNS = {...}` (Assign) and
        # `PATTERNS: dict[...] = {...}` (AnnAssign).
        value = None
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "PATTERNS" for t in node.targets
        ):
            value = node.value
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "PATTERNS"
        ):
            value = node.value
        if value is None:
            continue
        if not isinstance(value, ast.Dict):
            raise RuntimeError(f"{path}: PATTERNS is not a literal dict")
        for key_node, val_node in zip(value.keys, value.values):
            if not isinstance(key_node, ast.Constant) or not isinstance(key_node.value, str):
                raise RuntimeError(f"{path}: non-string PATTERNS key")
            if not isinstance(val_node, ast.Dict):
                raise RuntimeError(f"{path}: PATTERNS['{key_node.value}'] is not a dict")
            regex = None
            for inner_k, inner_v in zip(val_node.keys, val_node.values):
                if (isinstance(inner_k, ast.Constant) and inner_k.value == "regex"
                        and isinstance(inner_v, ast.Constant)):
                    regex = inner_v.value
                    break
            if regex is None:
                raise RuntimeError(
                    f"{path}: PATTERNS['{key_node.value}'] missing a literal 'regex'"
                )
            out[key_node.value] = regex
        return out
    raise RuntimeError(f"{path}: no top-level PATTERNS assignment found")


def main(argv: list[str]) -> int:
    verbose = "--verbose" in argv or "-v" in argv

    try:
        litellm_patterns = _extract_patterns(LITELLM_PATH)
        govhub_patterns = _extract_patterns(GOVHUB_PATH)
    except Exception as e:
        print(f"ERROR: pattern extraction failed: {e}", file=sys.stderr)
        return 2

    shared = set(litellm_patterns) & set(govhub_patterns)
    llm_only = set(litellm_patterns) - set(govhub_patterns)
    gov_only = set(govhub_patterns) - set(litellm_patterns)

    drifted: list[tuple[str, str, str]] = []
    for name in sorted(shared):
        if litellm_patterns[name] != govhub_patterns[name]:
            drifted.append((name, litellm_patterns[name], govhub_patterns[name]))

    if verbose:
        print(f"LiteLLM patterns:   {len(litellm_patterns)}")
        print(f"Gov-Hub patterns:   {len(govhub_patterns)}")
        print(f"Shared keys:        {len(shared)}")
        print(f"LiteLLM-only keys:  {sorted(llm_only) or 'none'}")
        print(f"Gov-Hub-only keys:  {sorted(gov_only) or 'none'}")

    status = 0

    if llm_only:
        # LiteLLM has a pattern the gov-hub doesn't. Usually a bug —
        # something new added upstream that should mirror downstream.
        print(
            "DLP DRIFT: patterns present in LiteLLM but missing from Gov-Hub:",
            file=sys.stderr,
        )
        for name in sorted(llm_only):
            print(f"  - {name}  regex={litellm_patterns[name]!r}", file=sys.stderr)
        status = 1

    if drifted:
        print("DLP DRIFT: regex mismatch on shared keys:", file=sys.stderr)
        for name, a, b in drifted:
            print(f"  ✗ {name}", file=sys.stderr)
            print(f"      litellm: {a!r}", file=sys.stderr)
            print(f"      govhub : {b!r}", file=sys.stderr)
        status = 1

    if status == 0:
        print(
            f"OK — {len(shared)} shared DLP patterns match across "
            f"dlp_guardrail.py and dlp_scan.py "
            f"(gov-hub-only extras: {len(gov_only)})"
        )

    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
