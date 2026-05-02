"""Celery tasks for document processing.

These tasks run inside the Celery worker process (completely separate from the
FastAPI process). They are CPU/IO-heavy and must NOT run inside the async event
loop of the web server.

Progress updates are published to Redis Pub/Sub so the FastAPI WebSocket
subscriber can forward them to connected browser clients in real-time.
"""

import asyncio
import logging

from app.worker import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="app.tasks.process_document_task",
    queue="document_ingestion",
    max_retries=2,
    default_retry_delay=10,
)
def process_document_task(self, file_path: str, filename: str, doc_id: str):
    """Celery task that runs the full document ingestion pipeline.

    Wraps the async `document_service.process_document` coroutine in a fresh
    asyncio event loop so it can be executed inside the synchronous Celery worker.
    """
    logger.info(f"[Task] Starting ingestion for doc_id={doc_id}, file={filename}")
    try:
        # Import here to avoid circular imports at module-level
        from app.services.document_service import process_document

        # Celery workers are synchronous; run the async pipeline in a new loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            # Load settings into the worker's memory cache before processing
            from app.services.settings_service import load_settings
            loop.run_until_complete(load_settings())

            result = loop.run_until_complete(
                process_document(file_path, filename, doc_id)
            )
        finally:
            loop.close()

        logger.info(f"[Task] ✅ Finished doc_id={doc_id}: {result} chunks stored")
        return {"doc_id": doc_id, "chunks": result}

    except Exception as exc:
        logger.error(f"[Task] ❌ Failed doc_id={doc_id}: {exc}")
        # Retry up to max_retries times before giving up
        raise self.retry(exc=exc)
