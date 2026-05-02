"""Memory / Personalization API endpoints."""

import logging
from fastapi import APIRouter, HTTPException

from app.models.schemas import (
    MemoryResponse,
    MemoryListResponse,
    MemoryCreateRequest,
    MemoryUpdateRequest,
    MemoryDeleteResponse,
)
from app.database import db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["Memory"])


@router.get("/memories", response_model=MemoryListResponse)
async def list_memories():
    """List all user memories (including disabled)."""
    memories = await db.get_all_memories()
    return MemoryListResponse(
        memories=[
            MemoryResponse(
                id=m["id"],
                content=m["content"],
                source=m.get("source", "auto"),
                active=bool(m.get("active", 1)),
                created_at=m["created_at"],
                updated_at=m["updated_at"],
            )
            for m in memories
        ],
        total=len(memories),
        limit=db.MAX_MEMORIES,
    )


@router.post("/memories", response_model=MemoryResponse, status_code=201)
async def create_memory(request: MemoryCreateRequest):
    """Manually create a new user memory."""
    mem_id = await db.insert_memory(request.content, source="manual")
    if not mem_id:
        raise HTTPException(
            status_code=400,
            detail=f"Memory limit reached ({db.MAX_MEMORIES}). Delete some memories first.",
        )

    # Fetch the created memory to return full data
    memories = await db.get_all_memories()
    mem = next((m for m in memories if m["id"] == mem_id), None)
    if not mem:
        raise HTTPException(status_code=500, detail="Failed to retrieve created memory")

    return MemoryResponse(
        id=mem["id"],
        content=mem["content"],
        source=mem.get("source", "manual"),
        active=bool(mem.get("active", 1)),
        created_at=mem["created_at"],
        updated_at=mem["updated_at"],
    )


@router.put("/memories/{mem_id}", response_model=MemoryResponse)
async def update_memory(mem_id: str, request: MemoryUpdateRequest):
    """Update a memory's content and/or active status."""
    updates = request.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    updated = await db.update_memory(
        mem_id,
        content=updates.get("content"),
        active=updates.get("active"),
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Memory not found")

    # Fetch updated memory
    memories = await db.get_all_memories()
    mem = next((m for m in memories if m["id"] == mem_id), None)
    if not mem:
        raise HTTPException(status_code=404, detail="Memory not found after update")

    return MemoryResponse(
        id=mem["id"],
        content=mem["content"],
        source=mem.get("source", "auto"),
        active=bool(mem.get("active", 1)),
        created_at=mem["created_at"],
        updated_at=mem["updated_at"],
    )


@router.delete("/memories/{mem_id}", response_model=MemoryDeleteResponse)
async def delete_memory(mem_id: str):
    """Delete a single memory."""
    deleted = await db.delete_memory(mem_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Memory not found")

    return MemoryDeleteResponse(deleted=True, message="Memory deleted")


@router.delete("/memories", response_model=MemoryDeleteResponse)
async def clear_all_memories():
    """Delete all user memories."""
    count = await db.clear_all_memories()
    return MemoryDeleteResponse(
        deleted=count > 0,
        message=f"Deleted {count} memories",
    )
