"""Pytest shared config for the governance-hub test suite.

Adds the `src/` package root to sys.path so tests import the real
service code without needing an editable install. The image doesn't
ship pyproject.toml; a `conftest.py` is the minimum boilerplate that
lets `pytest` find the module graph from either ./ or from tests/.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # configs/governance-hub
SRC = ROOT / "src"
# Expose `import src` and the parent so `from src.services.* import ...`
# works when pytest's rootdir is configs/governance-hub.
for p in (str(ROOT), str(SRC)):
    if p not in sys.path:
        sys.path.insert(0, p)
