"""Realtime helpers for broadcasting document state changes to connected clients.

Architecture:
  - Celery workers publish progress updates to a Redis Pub/Sub channel
    (``RAG_DOC_EVENTS``).
  - The FastAPI process runs an async subscriber that reads from that channel
    and forwards each message to every connected WebSocket client.
  - When Redis is unavailable (e.g. local dev without Docker), the subscriber
    silently skips and progress updates flow through the old in-process path.
"""

import asyncio
import json
import logging
import os
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)

# Redis Pub/Sub channel name shared between workers and the API process
REDIS_CHANNEL = "RAG_DOC_EVENTS"

# Connection string — same env var used by Celery so everything is consistent
REDIS_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")


def serialize_document(doc: dict[str, Any]) -> dict[str, Any]:
    """Normalize document records for API and websocket payloads."""
    return {
        "id": doc["id"],
        "filename": doc["filename"],
        "file_type": doc["file_type"],
        "file_size": doc["file_size"],
        "chunk_count": doc["chunk_count"],
        "status": doc["status"],
        "status_detail": doc.get("status_detail") or "",
        "progress": doc.get("progress") or 0,
        "upload_date": doc["upload_date"],
        "error_message": doc.get("error_message"),
    }


class DocumentEventsManager:
    """WebSocket connection manager + Redis Pub/Sub bridge.

    Clients connect via WebSocket; the background ``redis_subscriber`` task
    reads messages from the Redis channel and forwards them here.
    """

    def __init__(self):
        self._connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket):
        """Accept and register a websocket connection."""
        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)

    async def disconnect(self, websocket: WebSocket):
        """Remove a websocket connection if it exists."""
        async with self._lock:
            self._connections.discard(websocket)

    async def broadcast(self, payload: dict[str, Any]):
        """Broadcast a JSON payload to every active client."""
        async with self._lock:
            connections = list(self._connections)

        stale_connections: list[WebSocket] = []
        for connection in connections:
            try:
                await connection.send_json(payload)
            except Exception as exc:
                logger.debug("Dropping stale websocket connection: %s", exc)
                stale_connections.append(connection)

        if stale_connections:
            async with self._lock:
                for connection in stale_connections:
                    self._connections.discard(connection)

    # ── Redis Pub/Sub publish helper (called from worker via sync redis) ──────

    @staticmethod
    def publish_sync(payload: dict[str, Any]):
        """Publish a payload to the Redis Pub/Sub channel (sync, for Celery workers).

        This is a *synchronous* helper called from within the Celery worker process.
        It uses the blocking ``redis`` client so it works inside sync tasks.
        """
        try:
            import redis as _redis  # type: ignore

            r = _redis.from_url(REDIS_URL, decode_responses=True)
            r.publish(REDIS_CHANNEL, json.dumps(payload))
        except Exception as exc:
            # If Redis is down, log and continue — don't crash the worker
            logger.warning("Redis publish failed (non-fatal): %s", exc)


document_events = DocumentEventsManager()


async def redis_subscriber():
    """Long-running async task: subscribe to Redis Pub/Sub and forward events.

    Spawned once at app startup in ``main.py``. Uses ``redis.asyncio`` (the
    async client shipped with the ``redis`` package >= 4.2).

    If Redis is unavailable, it retries with exponential back-off so local dev
    without Redis still works (just without cross-process progress updates).
    """
    retry_delay = 2.0

    while True:
        try:
            import redis.asyncio as aioredis  # type: ignore

            r = aioredis.from_url(REDIS_URL, decode_responses=True)
            pubsub = r.pubsub()
            await pubsub.subscribe(REDIS_CHANNEL)
            logger.info(
                f"[RealtimeService] Subscribed to Redis channel '{REDIS_CHANNEL}' at {REDIS_URL}"
            )
            retry_delay = 2.0  # reset after successful connection

            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue
                try:
                    payload = json.loads(message["data"])
                    await document_events.broadcast(payload)
                except Exception as exc:
                    logger.debug("Failed to forward Redis message: %s", exc)

        except Exception as exc:
            logger.warning(
                f"[RealtimeService] Redis subscriber error ({exc}). "
                f"Retrying in {retry_delay:.0f}s..."
            )
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 30)  # exponential back-off, cap 30s
