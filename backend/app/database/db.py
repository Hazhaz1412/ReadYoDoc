"""SQLite database for document metadata tracking."""

import os
import aiosqlite
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Configurable via env for Docker volume mount
_db_dir = os.getenv("DB_DATA_PATH", str(Path(__file__).resolve().parent.parent.parent))
DB_PATH = Path(_db_dir) / "rag_metadata.db"


async def init_db():
    """Create the documents table if it doesn't exist."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                file_type TEXT NOT NULL,
                file_size INTEGER NOT NULL,
                chunk_count INTEGER DEFAULT 0,
                status TEXT DEFAULT 'processing',
                upload_date TEXT NOT NULL,
                file_path TEXT NOT NULL,
                error_message TEXT
            )
        """)
        await db.commit()


async def insert_document(
    filename: str,
    file_type: str,
    file_size: int,
    file_path: str,
) -> str:
    """Insert a new document record and return its ID."""
    doc_id = str(uuid.uuid4())
    upload_date = datetime.now(timezone.utc).isoformat()

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO documents (id, filename, file_type, file_size, status, upload_date, file_path)
               VALUES (?, ?, ?, ?, 'processing', ?, ?)""",
            (doc_id, filename, file_type, file_size, upload_date, file_path),
        )
        await db.commit()
    return doc_id


async def update_document_status(
    doc_id: str,
    status: str,
    chunk_count: int = 0,
    error_message: Optional[str] = None,
):
    """Update document processing status."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """UPDATE documents SET status = ?, chunk_count = ?, error_message = ? WHERE id = ?""",
            (status, chunk_count, error_message, doc_id),
        )
        await db.commit()


async def get_all_documents() -> list[dict]:
    """Retrieve all documents."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM documents ORDER BY upload_date DESC"
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_document(doc_id: str) -> Optional[dict]:
    """Retrieve a single document by ID."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM documents WHERE id = ?", (doc_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def delete_document(doc_id: str) -> bool:
    """Delete a document record. Returns True if found and deleted."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
        await db.commit()
        return cursor.rowcount > 0


async def get_document_count() -> int:
    """Get total number of documents."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM documents WHERE status = 'ready'"
        )
        row = await cursor.fetchone()
        return row[0] if row else 0
