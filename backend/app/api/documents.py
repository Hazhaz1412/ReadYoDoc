"""Document management API endpoints."""

import os
import logging
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from app.config import settings
from app.models.schemas import (
    DocumentResponse,
    DocumentListResponse,
    DocumentDeleteResponse,
)
from app.database import db
from app.services import document_service, vector_store
from app.services.realtime_service import document_events, serialize_document
from app.tasks import process_document_task

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/documents", tags=["Documents"])

# Ensure upload directory exists
UPLOAD_DIR = Path(settings.UPLOAD_DIR).resolve()
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@router.post("/upload", response_model=list[DocumentResponse])
async def upload_documents(
    files: list[UploadFile] = File(...),
):
    """Upload one or more documents for processing.

    Supported formats: PDF, DOCX, TXT, MD.
    Files are saved immediately and processing is dispatched to the Celery
    worker queue — the request returns instantly without waiting for ingestion.
    """
    responses = []

    for file in files:
        # Validate file extension
        ext = Path(file.filename or "").suffix.lower()
        if ext not in settings.ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type: {ext}. "
                       f"Allowed: {', '.join(settings.ALLOWED_EXTENSIONS)}",
            )

        # Validate file size
        contents = await file.read()
        if len(contents) > settings.MAX_FILE_SIZE_BYTES:
            raise HTTPException(
                status_code=400,
                detail=f"File too large: {file.filename}. "
                       f"Maximum size: {settings.MAX_FILE_SIZE_MB}MB",
            )

        # Save file to disk
        file_path = UPLOAD_DIR / f"{file.filename}"
        # Avoid overwriting: append number if exists
        counter = 1
        while file_path.exists():
            stem = Path(file.filename).stem
            file_path = UPLOAD_DIR / f"{stem}_{counter}{ext}"
            counter += 1

        with open(file_path, "wb") as f:
            f.write(contents)

        # Create database record (status: 'processing' / Queued for ingestion)
        doc_id = await db.insert_document(
            filename=file.filename or "unknown",
            file_type=ext,
            file_size=len(contents),
            file_path=str(file_path),
        )

        # ✨ Dispatch to Celery worker — returns immediately, never blocks the API
        process_document_task.delay(str(file_path), file.filename or "unknown", doc_id)
        logger.info(
            f"[Upload] Queued doc_id={doc_id} ({file.filename}) for Celery ingestion"
        )

        doc = await db.get_document(doc_id)
        if doc:
            responses.append(DocumentResponse(**serialize_document(doc)))
            await document_events.broadcast(
                {
                    "type": "document.created",
                    "document": serialize_document(doc),
                }
            )

    return responses


@router.get("", response_model=DocumentListResponse)
async def list_documents():
    """List all uploaded documents with their processing status."""
    docs = await db.get_all_documents()
    return DocumentListResponse(
        documents=[DocumentResponse(**serialize_document(d)) for d in docs],
        total=len(docs),
    )


@router.get("/{doc_id}", response_model=DocumentResponse)
async def get_document(doc_id: str):
    """Get details of a specific document."""
    doc = await db.get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    return DocumentResponse(**serialize_document(doc))


@router.delete("/{doc_id}", response_model=DocumentDeleteResponse)
async def delete_document(doc_id: str):
    """Delete a document and all its chunks from the vector database."""
    doc = await db.get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Remove chunks from ChromaDB
    chunks_deleted = vector_store.delete_document_chunks(doc_id)

    # Remove file from disk
    file_path = doc.get("file_path", "")
    if file_path and os.path.exists(file_path):
        os.remove(file_path)

    # Remove from database
    await db.delete_document(doc_id)
    await document_events.broadcast(
        {
            "type": "document.deleted",
            "document_id": doc_id,
        }
    )

    return DocumentDeleteResponse(
        id=doc_id,
        deleted=True,
        message=f"Deleted document '{doc['filename']}' and {chunks_deleted} chunks",
    )


@router.get("/download/{filename}")
async def download_document(filename: str):
    """Serve a document file."""
    # Prevent path traversal
    safe_filename = os.path.basename(filename)
    file_path = UPLOAD_DIR / safe_filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path=file_path)


@router.websocket("/ws")
async def documents_ws(websocket: WebSocket):
    """Push document list updates to connected clients."""
    await document_events.connect(websocket)
    try:
        docs = await db.get_all_documents()
        await websocket.send_json(
            {
                "type": "documents.snapshot",
                "documents": [serialize_document(doc) for doc in docs],
                "total": len(docs),
            }
        )

        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await document_events.disconnect(websocket)
