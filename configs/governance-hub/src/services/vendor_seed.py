"""Seed default ContributionTypes and the platform's own dependency vendors.

Runs idempotently on Governance Hub startup. Adds rows only if the table is
empty (or for a known seed slug, only if that slug is missing). Operators can
edit/delete/add freely after seed; we never overwrite admin changes.

The default vendors are the InsideLLM platform's own dependencies. Each
qualifies under the platform's Golden Rule that vendors used by the
platform must contribute to FOSS and/or recognized standards. Stars
awarded reflect the most directly verifiable contributions; admins are
expected to audit and refine over time.
"""
from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import (
    ContributionType,
    Vendor,
    VendorContribution,
)

logger = logging.getLogger("insidellm.vendor_seed")


# Each ContributionType is admin-editable after seed. We ship a starter set;
# add your own categories from the admin UI.
DEFAULT_CONTRIBUTION_TYPES = [
    {
        "code": "OSS_PROJECT",
        "name": "Maintains an open-source project",
        "description": "Vendor is the primary maintainer of an OSI-licensed project under active development.",
        "points": 1,
        "sort_order": 10,
    },
    {
        "code": "STANDARDS_BODY",
        "name": "Active in a recognized standards body",
        "description": "Vendor sits on or contributes to a recognized standards committee (CNCF TAG, IETF, W3C, NIST, IEEE, ISO).",
        "points": 1,
        "sort_order": 20,
    },
    {
        "code": "FOUNDATION_SPONSOR",
        "name": "Sponsors an open-source foundation",
        "description": "Vendor financially sponsors a recognized OSS foundation (CNCF, Linux Foundation, Apache, OpenSSF, etc).",
        "points": 1,
        "sort_order": 30,
    },
    {
        "code": "EMPLOYS_MAINTAINERS",
        "name": "Employs OSS maintainers full-time",
        "description": "Vendor pays full-time salaries for engineers whose primary work is upstream open-source contribution.",
        "points": 1,
        "sort_order": 40,
    },
    {
        "code": "PERMISSIVE_LICENSE",
        "name": "Releases own work under permissive license",
        "description": "Vendor publishes its core platform/SDKs/tools under MIT, Apache 2.0, BSD, or similar permissive license (not source-available BSL-only).",
        "points": 1,
        "sort_order": 50,
    },
    {
        "code": "TRANSPARENCY_PUBLICATION",
        "name": "Publishes safety / responsible-disclosure research",
        "description": "Vendor publishes substantive technical research (model cards, safety reports, post-mortems, threat models) for community benefit.",
        "points": 1,
        "sort_order": 60,
    },
    {
        "code": "BUG_BOUNTY",
        "name": "Runs a public bug-bounty program",
        "description": "Vendor maintains a public, paid bug-bounty channel with documented disclosure terms.",
        "points": 1,
        "sort_order": 70,
    },
]


# Each entry: vendor + list of (contribution_code, evidence_url, evidence_desc).
# evidence_url is what an auditor would click to verify the claim.
DEFAULT_VENDORS = [
    {
        "slug": "anthropic",
        "name": "Anthropic",
        "category": "ai-model",
        "website_url": "https://www.anthropic.com",
        "description": "Provider of the Claude model family. The frontier LLM behind every chat the platform serves.",
        "contributions": [
            ("TRANSPARENCY_PUBLICATION", "https://www.anthropic.com/research", "Publishes ongoing AI safety research, model cards, and Responsible Scaling Policy."),
            ("STANDARDS_BODY", "https://www.modelcontextprotocol.io", "Authored and stewards the Model Context Protocol (MCP) open standard."),
            ("BUG_BOUNTY", "https://hackerone.com/anthropic", "Public HackerOne bug-bounty program."),
        ],
    },
    {
        "slug": "postgresql",
        "name": "PostgreSQL Global Development Group",
        "category": "database",
        "website_url": "https://www.postgresql.org",
        "description": "The relational database backing LiteLLM, Open WebUI, and the Governance Hub.",
        "contributions": [
            ("OSS_PROJECT", "https://github.com/postgres/postgres", "Primary maintainer of PostgreSQL under the PostgreSQL License (BSD-style)."),
            ("PERMISSIVE_LICENSE", "https://www.postgresql.org/about/licence/", "PostgreSQL License is OSI-approved permissive."),
        ],
    },
    {
        "slug": "redis",
        "name": "Redis (community fork: Valkey at LF)",
        "category": "cache",
        "website_url": "https://valkey.io",
        "description": "In-memory cache + rate-limit state store. Currently the Redis 7.x line; community is migrating to Valkey under the Linux Foundation.",
        "contributions": [
            ("OSS_PROJECT", "https://github.com/valkey-io/valkey", "Valkey under Linux Foundation, BSD-3-Clause."),
            ("FOUNDATION_SPONSOR", "https://www.linuxfoundation.org/projects/valkey", "Sponsored by the Linux Foundation."),
        ],
    },
    {
        "slug": "nginx",
        "name": "F5 / NGINX",
        "category": "web-server",
        "website_url": "https://nginx.org",
        "description": "TLS terminator and reverse proxy in front of every InsideLLM service.",
        "contributions": [
            ("OSS_PROJECT", "https://nginx.org/en/download.html", "NGINX open-source under BSD 2-Clause."),
            ("PERMISSIVE_LICENSE", "https://nginx.org/LICENSE", "BSD 2-Clause."),
        ],
    },
    {
        "slug": "open-policy-agent",
        "name": "Open Policy Agent (CNCF / Apple)",
        "category": "policy-engine",
        "website_url": "https://www.openpolicyagent.org",
        "description": "Policy engine for Humility + industry overlays. Maintainers now at Apple, project under CNCF graduated status.",
        "contributions": [
            ("OSS_PROJECT", "https://github.com/open-policy-agent/opa", "OPA under Apache 2.0."),
            ("PERMISSIVE_LICENSE", "https://github.com/open-policy-agent/opa/blob/main/LICENSE", "Apache 2.0."),
            ("STANDARDS_BODY", "https://www.cncf.io/projects/open-policy-agent-opa/", "CNCF graduated project."),
            ("EMPLOYS_MAINTAINERS", "https://blog.openpolicyagent.org/note-from-teemu-tim-and-torin-to-the-open-policy-agent-community-2dbbfe494371", "Apple now employs the principal OPA maintainers full-time."),
        ],
    },
    {
        "slug": "grafana-labs",
        "name": "Grafana Labs",
        "category": "observability",
        "website_url": "https://grafana.com",
        "description": "Maintains Grafana, Loki, Promtail, Tempo. The observability stack for compliance dashboards and log aggregation.",
        "contributions": [
            ("OSS_PROJECT", "https://github.com/grafana/grafana", "Grafana under AGPL-3.0."),
            ("EMPLOYS_MAINTAINERS", "https://grafana.com/about/team/", "Employs full-time engineers on Grafana, Loki, Mimir, Tempo, Pyroscope."),
        ],
    },
    {
        "slug": "open-webui",
        "name": "Open WebUI",
        "category": "frontend",
        "website_url": "https://openwebui.com",
        "description": "The chat frontend employees actually see. Active community-driven project.",
        "contributions": [
            ("OSS_PROJECT", "https://github.com/open-webui/open-webui", "Open WebUI under MIT (with branding restrictions per their license addendum)."),
            ("PERMISSIVE_LICENSE", "https://github.com/open-webui/open-webui/blob/main/LICENSE", "MIT-derived license."),
        ],
    },
    {
        "slug": "berriai-litellm",
        "name": "BerriAI / LiteLLM",
        "category": "ai-gateway",
        "website_url": "https://www.litellm.ai",
        "description": "The model gateway that DLP, Humility, OPA, and budget enforcement plug into. Without LiteLLM there is no platform.",
        "contributions": [
            ("OSS_PROJECT", "https://github.com/BerriAI/litellm", "LiteLLM proxy + SDK under MIT."),
            ("PERMISSIVE_LICENSE", "https://github.com/BerriAI/litellm/blob/main/LICENSE", "MIT."),
        ],
    },
    {
        "slug": "docker",
        "name": "Docker, Inc.",
        "category": "container-runtime",
        "website_url": "https://www.docker.com",
        "description": "Container runtime + Compose. The packaging and orchestration foundation.",
        "contributions": [
            ("OSS_PROJECT", "https://github.com/moby/moby", "Moby (Docker Engine core) under Apache 2.0."),
            ("STANDARDS_BODY", "https://opencontainers.org", "Founding member of the Open Container Initiative."),
        ],
    },
    {
        "slug": "canonical-ubuntu",
        "name": "Canonical / Ubuntu",
        "category": "operating-system",
        "website_url": "https://ubuntu.com",
        "description": "The Linux distribution every InsideLLM VM boots from.",
        "contributions": [
            ("OSS_PROJECT", "https://launchpad.net/ubuntu", "Ubuntu under various OSS licenses; Canonical maintains the distribution and many upstream projects."),
            ("EMPLOYS_MAINTAINERS", "https://canonical.com/careers", "Employs full-time engineers across kernel, GNOME, MicroK8s, snapd, cloud-init, and other upstream projects."),
        ],
    },
    {
        "slug": "uniformedi",
        "name": "Uniformedi LLC",
        "category": "platform",
        "website_url": "https://github.com/Uniformedi",
        "description": "Maintainer of InsideLLM and the SAIVAS / Humility framework.",
        "contributions": [
            ("OSS_PROJECT", "https://github.com/Uniformedi/humility-guardrail", "humility-guardrail under MIT."),
            ("PERMISSIVE_LICENSE", "https://github.com/Uniformedi/humility-guardrail/blob/main/LICENSE", "MIT (canonical Humility implementation)."),
            ("TRANSPARENCY_PUBLICATION", "https://github.com/Uniformedi/InsideLLM/tree/master/docs", "Publishes architecture and integrity-design documentation."),
        ],
    },
]


async def seed_vendors(db: AsyncSession) -> None:
    """Idempotent — never overwrites existing rows."""
    # ContributionTypes: insert any missing by code
    type_by_code: dict[str, int] = {}
    for ct in DEFAULT_CONTRIBUTION_TYPES:
        existing = await db.execute(
            select(ContributionType).where(ContributionType.code == ct["code"])
        )
        row = existing.scalar_one_or_none()
        if row:
            type_by_code[ct["code"]] = row.id
            continue
        new = ContributionType(**ct)
        db.add(new)
        await db.flush()
        type_by_code[ct["code"]] = new.id
        logger.info(f"seeded contribution type: {ct['code']}")

    # Vendors: insert any missing by slug, with their contributions
    for v in DEFAULT_VENDORS:
        existing = await db.execute(select(Vendor).where(Vendor.slug == v["slug"]))
        row = existing.scalar_one_or_none()
        if row:
            continue  # never overwrite admin-curated state

        contribs = v.pop("contributions", [])
        v_data = {k: vv for k, vv in v.items() if k != "contributions"}
        # Restore contributions list back into the dict for future re-seed reasoning;
        # the list comprehension above already pulled it.
        vendor = Vendor(**v_data)
        db.add(vendor)
        await db.flush()

        for code, evidence_url, evidence_desc in contribs:
            type_id = type_by_code.get(code)
            if not type_id:
                logger.warning(f"unknown contribution type {code} for {v_data['slug']}")
                continue
            db.add(VendorContribution(
                vendor_id=vendor.id,
                contribution_type_id=type_id,
                evidence_url=evidence_url,
                evidence_description=evidence_desc,
                awarded_by="seed",
                awarded_at=datetime.utcnow(),
            ))
        vendor.total_stars = len(contribs)
        logger.info(f"seeded vendor: {v_data['slug']} ({len(contribs)} stars)")

    await db.commit()
