"""Celery task modules for async declarative-agent actions (P3.3).

Every task here is registered under `insidellm.tasks.<name>` via the
shared Celery app in src.celery_app. Task catalog entries set
`backend.task = "insidellm.tasks.<name>"` to route here.

Naming convention:
  * `*_batch_*` names route to the `bulk` queue (see celery_app task_routes)
  * Everything else lands on the default `actions` queue

Keep tasks deterministic + idempotent when possible — `task_acks_late`
means a crashed worker's job will be re-delivered.
"""
from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from .celery_app import app

logger = logging.getLogger("insidellm.tasks")


# ---------------------------------------------------------------------------
# batch_letter_merge — bulk route
# ---------------------------------------------------------------------------


@app.task(
    name="insidellm.tasks.batch_letter_merge",
    bind=True,
    max_retries=1,
    acks_late=True,
)
def batch_letter_merge(self, *, account_numbers: list[str], letter_template_id: str) -> dict[str, Any]:
    """Generate one letter per account number and return a manifest of
    artifacts. Long-running — routed to the `bulk` queue. Intended for
    end-of-cycle campaigns (post-settlement notices, late-stage validation).

    The demo implementation is deterministic: it returns a stub artifact
    manifest so downstream integration tests can assert shape. Real
    deployments replace this task via `Celery app.conf.include = [...]`.
    """
    total = len(account_numbers or [])
    logger.info(
        f"batch_letter_merge start task_id={self.request.id} "
        f"template={letter_template_id} n={total}"
    )

    artifacts: list[dict[str, Any]] = []
    for i, acct in enumerate(account_numbers or []):
        # Simulate per-letter work at ~40ms to keep demo runs reasonable.
        time.sleep(0.04)
        artifacts.append({
            "account_number": acct,
            "letter_id": str(uuid.uuid4()),
            "template_id": letter_template_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        })
        # Celery progress updates — tasks can be polled for "PROGRESS" state.
        if i % 25 == 0:
            self.update_state(
                state="PROGRESS",
                meta={"processed": i + 1, "total": total},
            )

    return {
        "ok": True,
        "count": len(artifacts),
        "artifacts": artifacts,
        "template_id": letter_template_id,
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# ocr_document — default queue
# ---------------------------------------------------------------------------


@app.task(
    name="insidellm.tasks.ocr_document",
    bind=True,
    max_retries=2,
    default_retry_delay=15,
)
def ocr_document(self, *, document_url: str, language: str = "eng") -> dict[str, Any]:
    """Run OCR over a document. Idempotent: same URL → same result, so
    retries are safe. Demo mode returns stub text.
    """
    logger.info(
        f"ocr_document task_id={self.request.id} url={document_url} lang={language}"
    )
    # Simulate 2s of OCR work.
    time.sleep(2.0)
    return {
        "ok": True,
        "document_url": document_url,
        "language": language,
        "text": "[demo-ocr] redacted placeholder text — replace with real Tesseract output",
        "page_count": 1,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# account_portfolio_export — default queue
# ---------------------------------------------------------------------------


@app.task(
    name="insidellm.tasks.account_portfolio_export",
    bind=True,
    acks_late=True,
)
def account_portfolio_export(
    self,
    *,
    tenant_id: str,
    cutoff_date: str | None = None,
) -> dict[str, Any]:
    """Export a tenant's account portfolio for a dashboard / reporting pull.
    Stub returns a single-row manifest; production wires this to the
    tenant's data connector.
    """
    logger.info(
        f"account_portfolio_export task_id={self.request.id} tenant={tenant_id} cutoff={cutoff_date}"
    )
    time.sleep(0.5)
    return {
        "ok": True,
        "tenant_id": tenant_id,
        "cutoff_date": cutoff_date or datetime.now(timezone.utc).date().isoformat(),
        "rows": 0,
        "export_url": None,
        "note": "demo stub — wire to tenant data-connector in production",
    }
