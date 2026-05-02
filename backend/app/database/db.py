"""SQLite database for document metadata tracking."""

import os
import aiosqlite
import uuid
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Configurable via env for Docker volume mount
_db_dir = os.getenv("DB_DATA_PATH", str(Path(__file__).resolve().parent.parent.parent))
DB_PATH = Path(_db_dir) / "rag_metadata.db"


async def init_db():
    """Create the documents table if it doesn't exist."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                file_type TEXT NOT NULL,
                file_size INTEGER NOT NULL,
                chunk_count INTEGER DEFAULT 0,
                status TEXT DEFAULT 'processing',
                status_detail TEXT DEFAULT '',
                progress INTEGER DEFAULT 0,
                upload_date TEXT NOT NULL,
                file_path TEXT NOT NULL,
                error_message TEXT
            )
        """)
        cursor = await db.execute("PRAGMA table_info(documents)")
        columns = {row[1] for row in await cursor.fetchall()}
        if "status_detail" not in columns:
            await db.execute(
                "ALTER TABLE documents ADD COLUMN status_detail TEXT DEFAULT ''"
            )
        if "progress" not in columns:
            await db.execute(
                "ALTER TABLE documents ADD COLUMN progress INTEGER DEFAULT 0"
            )

        # Conversation memory tables
        await db.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                title TEXT DEFAULT 'New Chat',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS chat_messages (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                sources TEXT DEFAULT '[]',
                created_at TEXT NOT NULL,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
            )
        """)
        cursor = await db.execute("PRAGMA table_info(chat_messages)")
        columns = {row[1] for row in await cursor.fetchall()}
        if "sources" not in columns:
            await db.execute("ALTER TABLE chat_messages ADD COLUMN sources TEXT DEFAULT '[]'")

        # System Settings table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS system_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)

        # User Memories table (personalization)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_memories (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                source TEXT DEFAULT 'auto',
                active INTEGER DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        await db.commit()


async def get_all_settings() -> dict:
    """Retrieve all system settings as a dictionary."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT key, value FROM system_settings")
        rows = await cursor.fetchall()
        return {row[0]: row[1] for row in rows}


async def get_setting(key: str, default: str = None) -> str:
    """Retrieve a single setting by key."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT value FROM system_settings WHERE key = ?", (key,))
        row = await cursor.fetchone()
        return row[0] if row else default


async def set_setting(key: str, value: str):
    """Insert or update a setting."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO system_settings (key, value)
               VALUES (?, ?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
            (key, value),
        )
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
            """INSERT INTO documents (
                   id, filename, file_type, file_size, status, status_detail, progress, upload_date, file_path
               )
               VALUES (?, ?, ?, ?, 'processing', ?, ?, ?, ?)""",
            (doc_id, filename, file_type, file_size, "Queued for ingestion", 5, upload_date, file_path),
        )
        await db.commit()
    return doc_id


async def update_document_status(
    doc_id: str,
    status: str,
    chunk_count: int = 0,
    error_message: Optional[str] = None,
    status_detail: str = "",
    progress: int = 0,
):
    """Update document processing status."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """UPDATE documents
               SET status = ?, chunk_count = ?, error_message = ?, status_detail = ?, progress = ?
               WHERE id = ?""",
            (status, chunk_count, error_message, status_detail, progress, doc_id),
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


# ─── Conversation CRUD ──────────────────────────────────────────


async def create_conversation(title: str = "New Chat") -> str:
    """Create a new conversation and return its ID."""
    conv_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (conv_id, title, now, now),
        )
        await db.commit()
    return conv_id


async def get_conversations() -> list[dict]:
    """Retrieve all conversations, most recent first."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT c.*, COUNT(m.id) as message_count
            FROM conversations c
            LEFT JOIN chat_messages m ON m.conversation_id = c.id
            GROUP BY c.id
            ORDER BY c.updated_at DESC
        """)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_conversation(conv_id: str) -> Optional[dict]:
    """Retrieve a single conversation by ID."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM conversations WHERE id = ?", (conv_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def delete_conversation(conv_id: str) -> bool:
    """Delete a conversation and all its messages (CASCADE)."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        cursor = await db.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
        await db.commit()
        return cursor.rowcount > 0


async def update_conversation_title(conv_id: str, title: str):
    """Update the title of a conversation."""
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
            (title, now, conv_id),
        )
        await db.commit()


async def touch_conversation(conv_id: str):
    """Update the updated_at timestamp of a conversation."""
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (now, conv_id),
        )
        await db.commit()


# ─── Chat Messages CRUD ─────────────────────────────────────────


async def insert_chat_message(
    conversation_id: str,
    role: str,
    content: str,
    sources: list[dict] | None = None,
) -> str:
    """Insert a chat message and return its ID."""
    msg_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    sources_str = json.dumps(sources) if sources else "[]"

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO chat_messages (id, conversation_id, role, content, sources, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (msg_id, conversation_id, role, content, sources_str, now),
        )
        await db.commit()

    # Touch the conversation's updated_at
    await touch_conversation(conversation_id)
    return msg_id


async def get_conversation_messages(
    conversation_id: str,
    limit: int = 20,
) -> list[dict]:
    """Get the most recent messages for a conversation.

    Returns messages in chronological order (oldest first),
    limited to the N most recent messages.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        # Subquery: get latest N messages, then order chronologically
        cursor = await db.execute(
            """SELECT * FROM (
                   SELECT id, conversation_id, role, content, sources, created_at
                   FROM chat_messages
                   WHERE conversation_id = ?
                   ORDER BY created_at DESC
                   LIMIT ?
               ) sub ORDER BY created_at ASC""",
            (conversation_id, limit),
        )
        rows = await cursor.fetchall()
        result = []
        for row in rows:
            d = dict(row)
            try:
                d["sources"] = json.loads(d.get("sources", "[]") or "[]")
            except Exception:
                d["sources"] = []
            result.append(d)
        return result


# ─── User Memories CRUD (Personalization) ────────────────────────

MAX_MEMORIES = 50


async def insert_memory(content: str, source: str = "auto") -> str:
    """Insert a new user memory. Returns its ID or empty string if limit reached."""
    async with aiosqlite.connect(DB_PATH) as conn:
        cursor = await conn.execute("SELECT COUNT(*) FROM user_memories")
        count = (await cursor.fetchone())[0]
        if count >= MAX_MEMORIES:
            return ""

        mem_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        await conn.execute(
            """INSERT INTO user_memories (id, content, source, active, created_at, updated_at)
               VALUES (?, ?, ?, 1, ?, ?)""",
            (mem_id, content, source, now, now),
        )
        await conn.commit()
    return mem_id


async def get_active_memories() -> list[dict]:
    """Get all active memories for prompt injection."""
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute(
            "SELECT * FROM user_memories WHERE active = 1 ORDER BY created_at ASC"
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_all_memories() -> list[dict]:
    """Get all memories including disabled ones."""
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute(
            "SELECT * FROM user_memories ORDER BY created_at DESC"
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def update_memory(
    mem_id: str,
    content: str | None = None,
    active: bool | None = None,
) -> bool:
    """Update a memory's content and/or active status."""
    parts, params = [], []
    now = datetime.now(timezone.utc).isoformat()

    if content is not None:
        parts.append("content = ?")
        params.append(content)
    if active is not None:
        parts.append("active = ?")
        params.append(1 if active else 0)

    if not parts:
        return False

    parts.append("updated_at = ?")
    params.append(now)
    params.append(mem_id)

    async with aiosqlite.connect(DB_PATH) as conn:
        cursor = await conn.execute(
            f"UPDATE user_memories SET {', '.join(parts)} WHERE id = ?",
            params,
        )
        await conn.commit()
        return cursor.rowcount > 0


async def delete_memory(mem_id: str) -> bool:
    """Delete a single memory."""
    async with aiosqlite.connect(DB_PATH) as conn:
        cursor = await conn.execute(
            "DELETE FROM user_memories WHERE id = ?", (mem_id,)
        )
        await conn.commit()
        return cursor.rowcount > 0


async def clear_all_memories() -> int:
    """Delete all memories. Returns count deleted."""
    async with aiosqlite.connect(DB_PATH) as conn:
        cursor = await conn.execute("DELETE FROM user_memories")
        await conn.commit()
        return cursor.rowcount


async def get_memory_count() -> int:
    """Get total number of memories."""
    async with aiosqlite.connect(DB_PATH) as conn:
        cursor = await conn.execute("SELECT COUNT(*) FROM user_memories")
        row = await cursor.fetchone()
        return row[0] if row else 0


