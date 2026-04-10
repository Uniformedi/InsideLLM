import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from .config import settings
from .db.local_db import AsyncSessionLocal, engine
from .db.models import Base
from .routers import advisor, audit, auth, changes, config_snapshots, connectors, fleet, obligations, restore, schema, sync
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

if settings.admin_auth_mode != "none":
    app.include_router(auth.router)

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


@app.get("/", response_class=HTMLResponse)
async def landing():
    """Governance Hub landing page with links to admin UI and API docs."""
    return f"""<!DOCTYPE html>
<html><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>InsideLLM — Governance Hub</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family:'Segoe UI',system-ui,sans-serif; background:#0a0e1a; color:#e2e8f0; min-height:100vh;
         display:flex; align-items:center; justify-content:center; }}
  .card {{ background:#1a2234; border:1px solid #2a3650; border-radius:12px; padding:48px; max-width:560px; width:90vw; }}
  h1 {{ font-size:24px; color:#22d3ee; font-family:monospace; margin-bottom:4px; }}
  .sub {{ color:#94a3b8; font-size:14px; margin-bottom:32px; }}
  .meta {{ display:flex; gap:16px; flex-wrap:wrap; margin-bottom:28px; }}
  .meta span {{ font-family:monospace; font-size:12px; background:#111827; border:1px solid #2a3650;
                padding:4px 10px; border-radius:4px; color:#94a3b8; }}
  .meta span strong {{ color:#22d3ee; }}
  .links {{ display:flex; flex-direction:column; gap:10px; }}
  a {{ display:flex; align-items:center; gap:12px; padding:14px 18px; background:#111827; border:1px solid #2a3650;
       border-radius:8px; text-decoration:none; color:#e2e8f0; transition:border-color 0.2s; }}
  a:hover {{ border-color:#22d3ee; }}
  a .icon {{ width:36px; height:36px; border-radius:8px; display:flex; align-items:center; justify-content:center;
             font-size:14px; font-weight:700; color:#fff; font-family:monospace; flex-shrink:0; }}
  a .label {{ font-weight:600; font-size:14px; }}
  a .desc {{ font-size:12px; color:#94a3b8; margin-top:2px; }}
  .dot {{ width:8px; height:8px; border-radius:50%; background:#34d399; display:inline-block; margin-right:6px; }}
</style>
</head><body>
<div class="card">
  <h1>InsideLLM Governance Hub</h1>
  <div class="sub"><span class="dot"></span>Running &mdash; v{settings.platform_version}</div>
  <div class="meta">
    <span><strong>Instance:</strong> {settings.instance_name or settings.instance_id or 'local'}</span>
    <span><strong>Industry:</strong> {settings.industry}</span>
    <span><strong>Tier:</strong> {settings.governance_tier}</span>
    <span><strong>Classification:</strong> {settings.data_classification}</span>
  </div>
  <div class="links">
    <a href="/admin">
      <span class="icon" style="background:#2563eb">CC</span>
      <div><div class="label">Command Center</div><div class="desc">Governance dashboard, change management, fleet overview, monitoring</div></div>
    </a>
    <a href="/governance/docs">
      <span class="icon" style="background:#059669">API</span>
      <div><div class="label">API Documentation</div><div class="desc">Swagger UI — all governance, fleet, sync, and restore endpoints</div></div>
    </a>
    <a href="/governance/redoc">
      <span class="icon" style="background:#7c3aed">RD</span>
      <div><div class="label">ReDoc</div><div class="desc">Alternative API reference with schema details</div></div>
    </a>
    <a href="/governance/health">
      <span class="icon" style="background:#0891b2">HC</span>
      <div><div class="label">Health Check</div><div class="desc">JSON status, version, instance identity, governance metadata</div></div>
    </a>
    <a href="/grafana/">
      <span class="icon" style="background:#d97706">GR</span>
      <div><div class="label">Compliance Dashboards</div><div class="desc">Grafana — spend tracking, keyword analysis, audit trails, fleet overview</div></div>
    </a>
  </div>
</div>
</body></html>"""


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "governance-hub",
        "instance_id": settings.instance_id,
        "instance_name": settings.instance_name,
        "schema_version": settings.schema_version,
        "platform_version": settings.platform_version,
        "industry": settings.industry,
        "governance_tier": settings.governance_tier,
        "data_classification": settings.data_classification,
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
