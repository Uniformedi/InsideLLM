from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db.local_db import get_local_db
from ..db.models import SchemaVersion

router = APIRouter(prefix="/api/v1/schema", tags=["schema"])


@router.get("/current")
async def current_schema():
    return {"schema_version": settings.schema_version, "instance_id": settings.instance_id}


@router.get("/history")
async def schema_history(db: AsyncSession = Depends(get_local_db)):
    result = await db.execute(select(SchemaVersion).order_by(SchemaVersion.version.desc()))
    versions = result.scalars().all()
    return [{"version": v.version, "description": v.description, "applied_at": v.applied_at} for v in versions]
