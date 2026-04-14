"""Vendor Management API.

Public read access (any authenticated user can browse the catalog and toggle
their personal favorites). Mutations to vendors, contributions, and
contribution types require admin role.

The Golden Rule the platform enforces: vendors in the catalog must
contribute to FOSS and/or recognized standards. The contribution-type
catalog encodes what counts; admins extend it as needed.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.local_db import get_local_db
from ..db.models import (
    ContributionType,
    Vendor,
    VendorContribution,
    VendorFavorite,
)

router = APIRouter(prefix="/api/v1", tags=["vendors"])


# ----- DTOs ------------------------------------------------------------------

class VendorIn(BaseModel):
    slug: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str = Field(..., min_length=1, max_length=200)
    description: str = ""
    website_url: str = ""
    category: str = ""
    is_active: bool = True


class VendorPatch(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    website_url: Optional[str] = None
    category: Optional[str] = None
    is_active: Optional[bool] = None


class ContributionIn(BaseModel):
    contribution_type_id: int
    evidence_url: str = ""
    evidence_description: str = ""


class ContributionTypeIn(BaseModel):
    code: str = Field(..., min_length=1, max_length=50, pattern=r"^[A-Z][A-Z0-9_]*$")
    name: str
    description: str
    points: int = 1
    is_active: bool = True
    sort_order: int = 100


class ContributionTypePatch(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    points: Optional[int] = None
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None


# ----- Auth helpers ----------------------------------------------------------

def _caller(request: Request) -> str:
    return getattr(request.state, "user_id", "") or "unknown"


def _is_admin(request: Request) -> bool:
    return bool(getattr(request.state, "is_admin", False))


def _require_admin(request: Request) -> None:
    if not _is_admin(request):
        raise HTTPException(status_code=403, detail="Admin role required")


async def _refresh_stars(db: AsyncSession, vendor_id: int) -> int:
    """Recompute total_stars for a vendor by summing each contribution's points
    (1 by default; admins may set higher-weight types)."""
    result = await db.execute(
        select(func.coalesce(func.sum(ContributionType.points), 0))
        .select_from(VendorContribution)
        .join(ContributionType, ContributionType.id == VendorContribution.contribution_type_id)
        .where(VendorContribution.vendor_id == vendor_id)
    )
    total = int(result.scalar() or 0)
    vendor = (await db.execute(select(Vendor).where(Vendor.id == vendor_id))).scalar_one()
    vendor.total_stars = total
    await db.commit()
    return total


# ----- Vendor list / detail --------------------------------------------------

@router.get("/vendors")
async def list_vendors(
    request: Request,
    favorites_only: bool = False,
    category: Optional[str] = None,
    db: AsyncSession = Depends(get_local_db),
) -> dict:
    stmt = select(Vendor).where(Vendor.is_active.is_(True)).order_by(Vendor.total_stars.desc(), Vendor.name)
    if category:
        stmt = stmt.where(Vendor.category == category)
    rows = (await db.execute(stmt)).scalars().all()

    fav_ids: set[int] = set()
    user_id = _caller(request)
    if user_id and user_id != "unknown":
        fav_rows = (await db.execute(select(VendorFavorite.vendor_id).where(VendorFavorite.user_id == user_id))).scalars().all()
        fav_ids = set(fav_rows)

    out = []
    for v in rows:
        if favorites_only and v.id not in fav_ids:
            continue
        out.append({
            "id": v.id,
            "slug": v.slug,
            "name": v.name,
            "description": v.description,
            "website_url": v.website_url,
            "category": v.category,
            "total_stars": v.total_stars,
            "is_favorite": v.id in fav_ids,
        })
    return {"vendors": out, "count": len(out)}


@router.get("/vendors/{slug}")
async def get_vendor(slug: str, request: Request, db: AsyncSession = Depends(get_local_db)) -> dict:
    v = (await db.execute(select(Vendor).where(Vendor.slug == slug))).scalar_one_or_none()
    if not v:
        raise HTTPException(status_code=404, detail="Vendor not found")

    contribs = (await db.execute(
        select(VendorContribution, ContributionType)
        .join(ContributionType, ContributionType.id == VendorContribution.contribution_type_id)
        .where(VendorContribution.vendor_id == v.id)
        .order_by(VendorContribution.awarded_at.desc())
    )).all()

    user_id = _caller(request)
    is_fav = False
    if user_id and user_id != "unknown":
        fav = (await db.execute(select(VendorFavorite).where(
            (VendorFavorite.user_id == user_id) & (VendorFavorite.vendor_id == v.id)
        ))).scalar_one_or_none()
        is_fav = fav is not None

    return {
        "id": v.id,
        "slug": v.slug,
        "name": v.name,
        "description": v.description,
        "website_url": v.website_url,
        "category": v.category,
        "total_stars": v.total_stars,
        "is_favorite": is_fav,
        "contributions": [
            {
                "id": c.id,
                "type_code": ct.code,
                "type_name": ct.name,
                "points": ct.points,
                "evidence_url": c.evidence_url,
                "evidence_description": c.evidence_description,
                "awarded_at": c.awarded_at,
                "awarded_by": c.awarded_by,
            }
            for c, ct in contribs
        ],
    }


# ----- Vendor mutations (admin) ----------------------------------------------

@router.post("/vendors", status_code=201)
async def create_vendor(payload: VendorIn, request: Request, db: AsyncSession = Depends(get_local_db)) -> dict:
    _require_admin(request)
    if (await db.execute(select(Vendor).where(Vendor.slug == payload.slug))).scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Vendor '{payload.slug}' exists")
    v = Vendor(**payload.model_dump(), created_by=_caller(request))
    db.add(v)
    await db.commit()
    await db.refresh(v)
    return {"id": v.id, "slug": v.slug}


@router.patch("/vendors/{slug}")
async def update_vendor(slug: str, payload: VendorPatch, request: Request, db: AsyncSession = Depends(get_local_db)) -> dict:
    _require_admin(request)
    v = (await db.execute(select(Vendor).where(Vendor.slug == slug))).scalar_one_or_none()
    if not v:
        raise HTTPException(status_code=404, detail="Vendor not found")
    for k, val in payload.model_dump(exclude_unset=True).items():
        setattr(v, k, val)
    v.updated_at = datetime.utcnow()
    await db.commit()
    return {"updated": slug}


@router.delete("/vendors/{slug}")
async def delete_vendor(slug: str, request: Request, db: AsyncSession = Depends(get_local_db)) -> dict:
    _require_admin(request)
    v = (await db.execute(select(Vendor).where(Vendor.slug == slug))).scalar_one_or_none()
    if not v:
        raise HTTPException(status_code=404, detail="Vendor not found")
    # Cascade: drop contributions + favorites for this vendor
    await db.execute(
        VendorContribution.__table__.delete().where(VendorContribution.vendor_id == v.id)
    )
    await db.execute(
        VendorFavorite.__table__.delete().where(VendorFavorite.vendor_id == v.id)
    )
    await db.delete(v)
    await db.commit()
    return {"deleted": slug}


# ----- Contributions (admin) -------------------------------------------------

@router.post("/vendors/{slug}/contributions", status_code=201)
async def award_contribution(
    slug: str,
    payload: ContributionIn,
    request: Request,
    db: AsyncSession = Depends(get_local_db),
) -> dict:
    _require_admin(request)
    v = (await db.execute(select(Vendor).where(Vendor.slug == slug))).scalar_one_or_none()
    if not v:
        raise HTTPException(status_code=404, detail="Vendor not found")
    ct = (await db.execute(select(ContributionType).where(ContributionType.id == payload.contribution_type_id))).scalar_one_or_none()
    if not ct or not ct.is_active:
        raise HTTPException(status_code=400, detail="Unknown or inactive contribution type")
    c = VendorContribution(
        vendor_id=v.id,
        contribution_type_id=payload.contribution_type_id,
        evidence_url=payload.evidence_url,
        evidence_description=payload.evidence_description,
        awarded_by=_caller(request),
    )
    db.add(c)
    await db.commit()
    total = await _refresh_stars(db, v.id)
    return {"contribution_id": c.id, "vendor_total_stars": total}


@router.delete("/vendors/{slug}/contributions/{contribution_id}")
async def revoke_contribution(
    slug: str,
    contribution_id: int,
    request: Request,
    db: AsyncSession = Depends(get_local_db),
) -> dict:
    _require_admin(request)
    v = (await db.execute(select(Vendor).where(Vendor.slug == slug))).scalar_one_or_none()
    if not v:
        raise HTTPException(status_code=404, detail="Vendor not found")
    c = (await db.execute(select(VendorContribution).where(
        (VendorContribution.id == contribution_id) & (VendorContribution.vendor_id == v.id)
    ))).scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="Contribution not found")
    await db.delete(c)
    await db.commit()
    total = await _refresh_stars(db, v.id)
    return {"deleted": contribution_id, "vendor_total_stars": total}


# ----- Contribution Types (admin) -------------------------------------------

@router.get("/contribution-types")
async def list_contribution_types(db: AsyncSession = Depends(get_local_db)) -> dict:
    rows = (await db.execute(select(ContributionType).order_by(ContributionType.sort_order, ContributionType.name))).scalars().all()
    return {"types": [
        {"id": ct.id, "code": ct.code, "name": ct.name, "description": ct.description,
         "points": ct.points, "is_active": ct.is_active, "sort_order": ct.sort_order}
        for ct in rows
    ]}


@router.post("/contribution-types", status_code=201)
async def create_contribution_type(payload: ContributionTypeIn, request: Request, db: AsyncSession = Depends(get_local_db)) -> dict:
    _require_admin(request)
    if (await db.execute(select(ContributionType).where(ContributionType.code == payload.code))).scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Type '{payload.code}' exists")
    ct = ContributionType(**payload.model_dump())
    db.add(ct)
    await db.commit()
    await db.refresh(ct)
    return {"id": ct.id, "code": ct.code}


@router.patch("/contribution-types/{type_id}")
async def update_contribution_type(type_id: int, payload: ContributionTypePatch, request: Request, db: AsyncSession = Depends(get_local_db)) -> dict:
    _require_admin(request)
    ct = (await db.execute(select(ContributionType).where(ContributionType.id == type_id))).scalar_one_or_none()
    if not ct:
        raise HTTPException(status_code=404, detail="Type not found")
    for k, val in payload.model_dump(exclude_unset=True).items():
        setattr(ct, k, val)
    await db.commit()
    return {"updated": type_id}


@router.delete("/contribution-types/{type_id}")
async def delete_contribution_type(type_id: int, request: Request, db: AsyncSession = Depends(get_local_db)) -> dict:
    _require_admin(request)
    # Refuse if any vendor still uses it
    in_use = (await db.execute(select(func.count(VendorContribution.id)).where(
        VendorContribution.contribution_type_id == type_id
    ))).scalar() or 0
    if in_use:
        raise HTTPException(status_code=409, detail=f"Type in use by {in_use} contribution(s); revoke them first")
    ct = (await db.execute(select(ContributionType).where(ContributionType.id == type_id))).scalar_one_or_none()
    if not ct:
        raise HTTPException(status_code=404, detail="Type not found")
    await db.delete(ct)
    await db.commit()
    return {"deleted": type_id}


# ----- User favorites (any authenticated user) ------------------------------

@router.post("/vendors/{slug}/favorite")
async def toggle_favorite(slug: str, request: Request, payload: dict = Body(default={}), db: AsyncSession = Depends(get_local_db)) -> dict:
    user_id = _caller(request)
    if not user_id or user_id == "unknown":
        raise HTTPException(status_code=401, detail="Authentication required")
    v = (await db.execute(select(Vendor).where(Vendor.slug == slug))).scalar_one_or_none()
    if not v:
        raise HTTPException(status_code=404, detail="Vendor not found")
    fav = (await db.execute(select(VendorFavorite).where(
        (VendorFavorite.user_id == user_id) & (VendorFavorite.vendor_id == v.id)
    ))).scalar_one_or_none()
    if fav:
        await db.delete(fav)
        await db.commit()
        return {"slug": slug, "is_favorite": False}
    else:
        new = VendorFavorite(user_id=user_id, vendor_id=v.id, tag=payload.get("tag", ""))
        db.add(new)
        await db.commit()
        return {"slug": slug, "is_favorite": True}
