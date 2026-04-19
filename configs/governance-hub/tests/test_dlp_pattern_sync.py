"""Regression guard: DLP patterns in dlp_scan.py must mirror the
LiteLLM gateway's dlp_guardrail.py PATTERNS dict.

Why: the notification sidecar (P2.1) runs in the gov-hub container
which can't import LiteLLM, so PATTERNS is duplicated. A divergence
means a PII type gets blocked on LLM traffic but leaks into chat
notifications (or vice versa). This test fails loud when that happens.

Mechanism: runs scripts/check-dlp-pattern-sync.py as a subprocess, which
AST-parses both files. No runtime imports, so LiteLLM doesn't need to
be installed in the test environment.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "check-dlp-pattern-sync.py"


def test_dlp_patterns_do_not_drift():
    assert SCRIPT.exists(), f"drift-check script missing at {SCRIPT}"
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, (
        "DLP pattern drift detected between "
        "configs/litellm/callbacks/dlp_guardrail.py and "
        "configs/governance-hub/src/services/dlp_scan.py.\n\n"
        f"stdout:\n{proc.stdout}\n\nstderr:\n{proc.stderr}"
    )
