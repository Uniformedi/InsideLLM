"""Core-catalog wrapper loader (P1.3).

Ships the five existing Open WebUI Tools as declarative catalog actions:

  * DocForge              — file generation + conversion
  * Governance Advisor    — AI governance analysis + change review
  * Fleet Management      — fleet telemetry + restore planning
  * System Designer       — deployment + cost + fleet planning
  * Data Connector        — registered read-only data sources

Each tool's methods map to one action_id. Entries ship at `tenant_id=core`
and are idempotently seeded at gov-hub startup (+ via POST /seed-core).
"""
from __future__ import annotations

import logging
from pathlib import Path

from ..schemas.actions import ActionCatalogEntry
from .action_catalog_service import parse_multi_action_document

logger = logging.getLogger("governance-hub.actions.seed")

# Relative to this file: src/actions_seed/core/*.yaml
_SEED_DIR = Path(__file__).resolve().parent.parent / "actions_seed" / "core"

# Declaring the expected wrapper files makes it obvious at code-review
# time if someone drops a file or renames one without updating the
# manifest. Alphabetical; the loader sorts for deterministic ordering.
_WRAPPERS = (
    "activepieces_examples.yaml",
    "async_tasks.yaml",
    "data_connector.yaml",
    "docforge.yaml",
    "fleet_management.yaml",
    "governance_advisor.yaml",
    "n8n_examples.yaml",
    "system_designer.yaml",
)


def load_core_wrappers() -> list[ActionCatalogEntry]:
    """Parse every shipped wrapper file and return flat list of entries."""
    entries: list[ActionCatalogEntry] = []
    for name in _WRAPPERS:
        path = _SEED_DIR / name
        if not path.exists():
            logger.warning(f"core wrapper missing: {path}")
            continue
        try:
            body = path.read_text(encoding="utf-8")
            parsed = parse_multi_action_document(body, content_type="application/yaml")
            entries.extend(parsed)
            logger.info(f"core wrapper loaded: {name} ({len(parsed)} actions)")
        except Exception as e:
            logger.error(f"core wrapper parse failed for {name}: {type(e).__name__}: {e}")
    return entries
