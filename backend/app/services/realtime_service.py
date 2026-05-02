"""Realtime helpers for broadcasting document state changes to connected clients."""

import asyncio
import logging
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


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
    """Small websocket connection manager for document events."""

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


document_events = DocumentEventsManager()
