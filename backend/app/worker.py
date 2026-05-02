"""Celery application instance.

This module defines the Celery app used by both the FastAPI process (to dispatch
tasks) and the Celery worker process (to execute them).

The CELERY_BROKER_URL / CELERY_RESULT_BACKEND env vars are set via docker-compose.
"""

import os
from celery import Celery

BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")

celery_app = Celery(
    "rag_worker",
    broker=BROKER_URL,
    backend=RESULT_BACKEND,
    include=["app.tasks"],
)

celery_app.conf.update(
    # Route all document ingestion jobs to a dedicated queue
    task_routes={"app.tasks.process_document_task": {"queue": "document_ingestion"}},
    # Acknowledge task only after it completes (safe retry on crash)
    task_acks_late=True,
    # One task per worker process at a time (embedding is already memory-heavy)
    worker_prefetch_multiplier=1,
    # Result expiry: 1 hour (we use SQLite + WS anyway)
    result_expires=3600,
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)
