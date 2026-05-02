"""Document management API endpoints."""

import os
import shutil
import logging
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, HTTPException, BackgroundTasks

from app.config import settings
from app.models.schemas import (
    DocumentResponse,
    DocumentListResponse,
    DocumentDeleteResponse,
)
from app.database import db
from app.services import document_service, vector_store

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/documents", tags=["Documents"])

# Ensure upload directory exists
UPLOAD_DIR = Path(settings.UPLOAD_DIR).resolve()
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@router.post("/upload", response_model=list[DocumentResponse])
async def upload_documents(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
):
    """Upload one or more documents for processing.

    Supported formats: PDF, DOCX, TXT, MD.
    Files are saved and processing happens in the background.
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

        # Create database record
        doc_id = await db.insert_document(
            filename=file.filename or "unknown",
            file_type=ext,
            file_size=len(contents),
            file_path=str(file_path),
        )

        # Process in background
        background_tasks.add_task(
            document_service.process_document,
            str(file_path),
            file.filename or "unknown",
            doc_id,
        )

        responses.append(
            DocumentResponse(
                id=doc_id,
                filename=file.filename or "unknown",
                file_type=ext,
                file_size=len(contents),
                chunk_count=0,
                status="processing",
                upload_date="now",
            )
        )

    return responses


@router.get("", response_model=DocumentListResponse)
async def list_documents():
    """List all uploaded documents with their processing status."""
    docs = await db.get_all_documents()
    return DocumentListResponse(
        documents=[
            DocumentResponse(
                id=d["id"],
                filename=d["filename"],
                file_type=d["file_type"],
                file_size=d["file_size"],
                chunk_count=d["chunk_count"],
                status=d["status"],
                upload_date=d["upload_date"],
                error_message=d.get("error_message"),
            )
            for d in docs
        ],
        total=len(docs),
    )


@router.get("/{doc_id}", response_model=DocumentResponse)
async def get_document(doc_id: str):
    """Get details of a specific document."""
    doc = await db.get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    return DocumentResponse(
        id=doc["id"],
        filename=doc["filename"],
        file_type=doc["file_type"],
        file_size=doc["file_size"],
        chunk_count=doc["chunk_count"],
        status=doc["status"],
        upload_date=doc["upload_date"],
        error_message=doc.get("error_message"),
    )


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

    return DocumentDeleteResponse(
        id=doc_id,
        deleted=True,
        message=f"Deleted document '{doc['filename']}' and {chunks_deleted} chunks",
    )
