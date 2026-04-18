"""Celery app for async / queued declarative-agent actions (P3.3).

Runs as the `insidellm-celery-worker` container. Same image as the stub
FastAPI workers; different command:

    celery -A src.celery_app worker --loglevel=info --queues=actions

Broker + result backend: the platform's existing Redis service. One queue
per cadence tier (`actions` default; `bulk` for long-running batches).
Tasks register themselves via `src/tasks.py` import side-effect.

Action catalog entries that want async execution set:

    backend:
      type: celery_task
      task: "insidellm.tasks.batch_letter_merge"
      queue: actions
      timeout_seconds: 600
      retries: 1

The gov-hub's action_dispatcher looks up the entry, publishes to the
queue with the caller's inputs, and returns a task_id the caller polls
via `/api/v1/actions/status/{task_id}`.
"""
from __future__ import annotations

import os

from celery import Celery

_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://redis:6379/1")
_RESULT_URL = os.environ.get("CELERY_RESULT_BACKEND", "redis://redis:6379/2")

# Task names are namespaced under `insidellm.tasks.*` so action catalog
# entries can reference them by fully-qualified dotted path. The namespace
# is stable even if we later split tasks across multiple modules.
app = Celery(
    "insidellm",
    broker=_BROKER_URL,
    backend=_RESULT_URL,
    include=["src.tasks"],
)

app.conf.update(
    # JSON-only serialization — pickle is a supply-chain footgun when the
    # broker is shared with other services.
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],

    # Visibility: every task's progress is observable by task_id within the
    # result backend TTL.
    result_expires=60 * 60 * 24,   # 24h — plenty for long-running agents

    # Hard and soft limits — defense against runaway tasks. Per-task
    # overrides in tasks.py can raise/lower these.
    task_time_limit=60 * 15,       # hard kill at 15 minutes
    task_soft_time_limit=60 * 10,  # graceful cleanup at 10 minutes

    # Acknowledge AFTER the task finishes so a crashed worker's message
    # goes back on the queue — at-least-once semantics. Tasks that can't
    # be retried idempotently should opt out via `acks_late = False`.
    task_acks_late=True,
    worker_prefetch_multiplier=1,  # paired with acks_late so one worker
                                   # doesn't hoard a queue of long-running jobs

    # Queues — actions (default, short) and bulk (long-running batches).
    task_default_queue="actions",
    task_create_missing_queues=True,
    task_routes={
        "insidellm.tasks.*_batch_*": {"queue": "bulk"},
    },
)
