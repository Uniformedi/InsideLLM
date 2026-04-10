import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI

from .config import settings
from .db.local_db import AsyncSessionLocal, engine
from .db.models import Base
from .routers import advisor, audit, changes, config_snapshots, connectors, fleet, obligations, restore, schema, sync
from .services.config_service import capture_snapshot
from .services.sync_service import collect_telemetry, export_to_central

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("governance-hub")

app = FastAPI(
    title="InsideLLM Governance Hub",
    version="1.0.0",
    description="Enterprise AI governance management — sync, change management, and AI-powered advisory.",
)


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    from fastapi.openapi.utils import get_openapi
    schema = get_openapi(title=app.title, version=app.version, description=app.description, routes=app.routes)
    schema["openapi"] = "3.0.3"
    app.openapi_schema = schema
    return app.openapi_schema

app.openapi = custom_openapi

app.include_router(sync.router)
app.include_router(changes.router)
app.include_router(config_snapshots.router)
app.include_router(schema.router)
app.include_router(advisor.router)
app.include_router(audit.router)
app.include_router(fleet.router)
app.include_router(restore.router)
app.include_router(connectors.router)
app.include_router(obligations.router)

scheduler = AsyncIOScheduler()


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "governance-hub",
        "instance_id": settings.instance_id,
        "schema_version": settings.schema_version,
    }


async def scheduled_sync():
    """Periodic sync job."""
    try:
        async with AsyncSessionLocal() as db:
            telemetry = await collect_telemetry(db, days=1)
            log = await export_to_central(db, telemetry)
            logger.info(f"Scheduled sync: {log.status} ({log.records_exported} records)")
    except Exception as e:
        logger.error(f"Scheduled sync failed: {e}")


@app.on_event("startup")
async def startup():
    # Create local governance tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Governance tables created/verified")

    # Initial config snapshot
    try:
        async with AsyncSessionLocal() as db:
            await capture_snapshot(db, created_by="startup")
        logger.info("Initial config snapshot captured")
    except Exception as e:
        logger.warning(f"Failed to capture initial snapshot: {e}")

    # Start sync scheduler
    if settings.sync_schedule and settings.central_db_url:
        try:
            trigger = CronTrigger.from_crontab(settings.sync_schedule)
            scheduler.add_job(scheduled_sync, trigger, id="governance_sync")
            scheduler.start()
            logger.info(f"Sync scheduler started: {settings.sync_schedule}")
        except Exception as e:
            logger.error(f"Failed to start scheduler: {e}")

    # Sync on startup
    if settings.sync_on_startup and settings.central_db_url:
        asyncio.create_task(scheduled_sync())


@app.on_event("shutdown")
async def shutdown():
    scheduler.shutdown(wait=False)
