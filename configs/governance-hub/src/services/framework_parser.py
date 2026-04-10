"""
Framework parser — parses AI_Governance_Framework.md into structured sections
and maps automated compliance checks to framework sections.
"""

import logging
import re
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ..config import settings
from ..db.models import ComplianceStatus, FrameworkSection

logger = logging.getLogger("governance-hub.framework")

# =========================================================================
# Compliance check mapping — automated checks mapped to framework sections
# =========================================================================
# Each key is an automated_check_key stored on FrameworkSection.
# The check functions are implemented in compliance_checks.py (Phase 2).
# For Phase 1, we track which sections are automatable.

COMPLIANCE_CHECK_MAP = {
    "dlp_enforcement": {
        "description": "DLP pipeline is active and blocking sensitive data",
        "section_pattern": "Privacy and Data Protection",
    },
    "data_classification_set": {
        "description": "Data classification is explicitly configured",
        "section_pattern": "Data Classification",
    },
    "monitoring_active": {
        "description": "Uptime Kuma and Grafana health monitoring are running",
        "section_pattern": "Monitoring and Risk Management",
    },
    "ethics_officer_assigned": {
        "description": "AI Ethics Officer is assigned in the configuration",
        "section_pattern": "Organizational Structures",
    },
    "audit_chain_intact": {
        "description": "Hash-chained audit trail integrity verification passes",
        "section_pattern": "Accountability and Governance",
    },
    "cve_scanning_active": {
        "description": "Trivy CVE scanning has run within last 48 hours",
        "section_pattern": "Safety and Security",
    },
    "budget_controls_active": {
        "description": "LiteLLM budget and rate limit controls are configured",
        "section_pattern": "Cost and Usage",
    },
    "opa_policies_loaded": {
        "description": "OPA policy engine has Humility + industry policies loaded",
        "section_pattern": "Acceptable Use",
    },
    "vendor_config_present": {
        "description": "At least one LLM vendor/model is configured in LiteLLM",
        "section_pattern": "LLM Vendor",
    },
    "keyword_analysis_active": {
        "description": "Industry keyword analysis engine is running",
        "section_pattern": "Keyword",
    },
    "governance_tier_set": {
        "description": "Governance tier is explicitly configured (not default)",
        "section_pattern": "Materiality Threshold",
    },
    "rate_limiting_active": {
        "description": "Per-user rate limits are configured",
        "section_pattern": "Rate Limit",
    },
    "agentic_logging_active": {
        "description": "Centralized logging (Loki) is operational",
        "section_pattern": "Comprehensive Logging",
    },
    "kill_switch_available": {
        "description": "Container management (Watchtower) is responsive",
        "section_pattern": "Kill Switch",
    },
    "fleet_sync_active": {
        "description": "Fleet sync to central database is configured and recent",
        "section_pattern": "Fleet Management",
    },
}


def parse_framework_markdown(markdown_path: str) -> list[dict]:
    """Parse the governance framework markdown into structured sections.

    Returns a list of dicts with: section_number, title, parent_section,
    content_markdown, compliance_type, automated_check_key, sort_order.
    """
    path = Path(markdown_path)
    if not path.exists():
        logger.warning(f"Framework file not found: {markdown_path}")
        return []

    content = path.read_text(encoding="utf-8")
    lines = content.split("\n")

    sections: list[dict] = []
    current_section: dict | None = None
    section_counter = 0
    h2_counter = 0
    h3_counter = 0

    for line in lines:
        # Detect heading levels
        if line.startswith("## ") and not line.startswith("### "):
            # Save previous section
            if current_section:
                sections.append(current_section)

            h2_counter += 1
            h3_counter = 0
            title = line[3:].strip()
            section_number = str(h2_counter)
            section_counter += 1

            compliance_type = _classify_section(title)
            check_key = _find_check_key(title)

            current_section = {
                "section_number": section_number,
                "title": title,
                "parent_section": None,
                "content_markdown": "",
                "compliance_type": compliance_type,
                "automated_check_key": check_key,
                "sort_order": section_counter,
            }
        elif line.startswith("### "):
            # Save previous section
            if current_section:
                sections.append(current_section)

            h3_counter += 1
            title = line[4:].strip()
            section_number = f"{h2_counter}.{h3_counter}"
            section_counter += 1

            compliance_type = _classify_section(title)
            check_key = _find_check_key(title)

            current_section = {
                "section_number": section_number,
                "title": title,
                "parent_section": str(h2_counter),
                "content_markdown": "",
                "compliance_type": compliance_type,
                "automated_check_key": check_key,
                "sort_order": section_counter,
            }
        elif current_section is not None:
            current_section["content_markdown"] += line + "\n"

    # Save last section
    if current_section:
        sections.append(current_section)

    logger.info(f"Parsed {len(sections)} sections from framework document")
    return sections


def _classify_section(title: str) -> str:
    """Determine if a section is automated, manual_attestation, or informational."""
    title_lower = title.lower()

    # Informational sections (principles, philosophy, definitions)
    informational_keywords = [
        "executive summary", "definitions", "foundation principles",
        "core philosophy", "table of contents", "appendix", "reference",
        "document control", "business benefits", "roi framework",
        "sunset provision", "reauthorization",
    ]
    for kw in informational_keywords:
        if kw in title_lower:
            return "informational"

    # Check if any automated check maps to this section
    if _find_check_key(title):
        return "automated"

    # Default: requires manual attestation
    return "manual_attestation"


def _find_check_key(title: str) -> str | None:
    """Find an automated check key matching this section title."""
    title_lower = title.lower()
    for key, info in COMPLIANCE_CHECK_MAP.items():
        if info["section_pattern"].lower() in title_lower:
            return key
    return None


def seed_framework_sections(db: Session, version: int = 1) -> dict:
    """Parse the framework and seed sections into the database.

    Idempotent: clears existing sections for the version and re-seeds.
    """
    sections = parse_framework_markdown(settings.framework_path)
    if not sections:
        return {"success": False, "message": "No sections parsed from framework document", "count": 0}

    # Clear existing sections for this version
    db.execute(
        text("DELETE FROM governance_framework_sections WHERE framework_version = :v"),
        {"v": version},
    )

    created = 0
    for s in sections:
        section = FrameworkSection(
            section_number=s["section_number"],
            title=s["title"],
            parent_section=s["parent_section"],
            content_markdown=s["content_markdown"].strip(),
            compliance_type=s["compliance_type"],
            automated_check_key=s["automated_check_key"],
            framework_version=version,
            sort_order=s["sort_order"],
        )
        db.add(section)
        created += 1

    db.commit()

    # Initialize compliance status for all assessable sections
    result = db.execute(
        text("SELECT id FROM governance_framework_sections WHERE compliance_type != 'informational' AND framework_version = :v"),
        {"v": version},
    )
    for row in result:
        # Check if status already exists
        existing = db.execute(
            text("SELECT id FROM governance_compliance_status WHERE section_id = :sid ORDER BY assessed_at DESC LIMIT 1"),
            {"sid": row[0]},
        ).first()
        if not existing:
            status = ComplianceStatus(
                section_id=row[0],
                status="not_assessed",
                evidence_type=None,
                assessed_by="system",
            )
            db.add(status)

    db.commit()

    logger.info(f"Seeded {created} framework sections (version {version})")
    return {"success": True, "message": f"Seeded {created} sections", "count": created}
