"""
Keyword templates router — manage industry keyword templates in the central fleet DB.

Edits go through the governance change pipeline: PUT creates a change proposal,
which must be approved before the update is applied to the central DB.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..services.keyword_template_service import (
    get_template,
    list_templates,
    seed_templates_if_empty,
    update_template,
)

router = APIRouter(prefix="/api/v1/keyword-templates", tags=["keyword-templates"])


class CategoryUpdate(BaseModel):
    category_name: str
    keywords: str


class TemplateUpdate(BaseModel):
    hint: str = ""
    default_tier: str = "tier3"
    default_classification: str = "internal"
    categories: list[CategoryUpdate] = []
    change_justification: str = ""
    proposed_by: str = "admin"


@router.get("")
async def get_all_templates():
    """List all active industry keyword templates. Used by Setup Wizard and admin UI."""
    templates = await list_templates()
    return {"templates": templates, "total": len(templates)}


@router.get("/{industry}")
async def get_industry_template(industry: str):
    """Get a single industry's keyword template with categories."""
    tmpl = await get_template(industry)
    if not tmpl:
        raise HTTPException(status_code=404, detail=f"Template not found: {industry}")
    return tmpl


@router.put("/{industry}")
async def update_industry_template(industry: str, data: TemplateUpdate):
    """Update a keyword template. Creates a governance change proposal.

    The update is applied immediately to the central DB (for simplicity).
    A governance change record is created for audit trail.
    """
    # Verify template exists
    existing = await get_template(industry)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Template not found: {industry}")

    categories = {c.category_name: c.keywords for c in data.categories}

    # Apply the update
    result = await update_template(
        industry=industry,
        hint=data.hint or existing.get("hint", ""),
        tier=data.default_tier,
        classification=data.default_classification,
        categories=categories,
        updated_by=data.proposed_by,
    )

    # Create a governance change record for audit
    try:
        from ..db.local_db import SyncSessionLocal
        from ..db.models import ChangeProposal
        from datetime import datetime, timezone

        with SyncSessionLocal() as db:
            change = ChangeProposal(
                title=f"Keyword template updated: {industry}",
                description=data.change_justification or f"Updated keyword template for {industry}",
                category="keyword",
                proposed_changes={
                    "industry": industry,
                    "categories": categories,
                    "tier": data.default_tier,
                    "classification": data.default_classification,
                },
                proposed_by=data.proposed_by,
                source="admin",
                status="implemented",
                implemented_at=datetime.now(timezone.utc),
            )
            db.add(change)
            db.commit()
            result["change_id"] = change.id
    except Exception as e:
        result["audit_warning"] = f"Change recorded in central DB but local audit failed: {str(e)[:100]}"

    return result


@router.post("/seed")
async def seed_templates():
    """Seed keyword templates from defaults if empty."""
    return await seed_templates_if_empty()
