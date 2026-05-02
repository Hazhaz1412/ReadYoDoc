"""Chat, query, and conversation management API endpoints with SSE streaming."""

import json
import logging
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.config import settings
from app.models.schemas import (
    ChatRequest,
    ChatResponse,
    ConversationListResponse,
    ConversationResponse,
    ConversationDeleteResponse,
    SearchRequest,
    SearchResponse,
    SourceChunk,
)
from app.services import embedding_service, vector_store, llm_service
from app.database import db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["Chat"])


@router.post("/chat")
async def chat(request: ChatRequest):
    """Ask a question and get a streaming answer based on uploaded documents.

    Returns Server-Sent Events (SSE) with:
    - type=meta: Conversation metadata (sent first)
    - type=sources: Source citations
    - type=token: Individual answer tokens
    - type=done: Signal that generation is complete
    """
    # Check if we have any documents
    if vector_store.get_total_chunks() == 0:
        raise HTTPException(
            status_code=400,
            detail="No documents uploaded yet. Please upload documents first.",
        )

    # Resolve conversation
    conversation_id = request.conversation_id
    if not conversation_id:
        conversation_id = await db.create_conversation()
    else:
        # Verify it exists
        conv = await db.get_conversation(conversation_id)
        if not conv:
            conversation_id = await db.create_conversation()

    # Load conversation history
    memory_limit = min(request.memory_limit, settings.MEMORY_HARD_LIMIT)
    history = []
    if memory_limit > 0:
        history = await db.get_conversation_messages(conversation_id, limit=memory_limit)

    # Save the user message immediately
    await db.insert_chat_message(conversation_id, "user", request.query)

    # Auto-title on first message
    conv = await db.get_conversation(conversation_id)
    if conv and conv["title"] == "New Chat":
        # Use first 60 chars of the query as title
        title = request.query[:60].strip()
        if len(request.query) > 60:
            title += "..."
        await db.update_conversation_title(conversation_id, title)

    # Step 1: Generate embedding for the query
    try:
        query_embedding = await embedding_service.generate_embedding(request.query)
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"Embedding service error: {str(e)}",
        )

    # Step 2: Find similar chunks
    similar_chunks = vector_store.query_similar(query_embedding, top_k=request.top_k)

    if not similar_chunks:
        raise HTTPException(
            status_code=404,
            detail="No relevant content found in uploaded documents.",
        )

    # Step 3: Stream the answer
    async def event_stream():
        # Send conversation metadata first
        yield f"data: {json.dumps({'type': 'meta', 'data': {'conversation_id': conversation_id}})}\n\n"

        # Send sources
        sources_data = [
            {
                "content": c["content"][:200] + "..." if len(c["content"]) > 200 else c["content"],
                "source_file": c["source_file"],
                "page": c.get("page"),
                "chunk_index": c["chunk_index"],
                "relevance_score": c["relevance_score"],
            }
            for c in similar_chunks
        ]
        yield f"data: {json.dumps({'type': 'sources', 'data': sources_data})}\n\n"

        # Stream answer tokens and collect full response
        full_response = []
        async for token in llm_service.generate_answer_stream(
            request.query,
            similar_chunks,
            history=history,
            use_thinking=request.use_thinking,
        ):
            full_response.append(token)
            yield f"data: {json.dumps({'type': 'token', 'data': token})}\n\n"

        # Save assistant response to DB
        assistant_text = "".join(full_response)
        if assistant_text:
            await db.insert_chat_message(conversation_id, "assistant", assistant_text)

        # Signal completion
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/chat/search", response_model=SearchResponse)
async def search_similar(request: SearchRequest):
    """Search for similar document chunks without generating an answer.

    Useful for debugging and seeing what context the RAG system finds.
    """
    if vector_store.get_total_chunks() == 0:
        return SearchResponse(chunks=[], query=request.query)

    try:
        query_embedding = await embedding_service.generate_embedding(request.query)
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"Embedding service error: {str(e)}",
        )

    similar_chunks = vector_store.query_similar(query_embedding, top_k=request.top_k)

    return SearchResponse(
        chunks=[
            SourceChunk(
                content=c["content"],
                source_file=c["source_file"],
                page=c.get("page"),
                chunk_index=c["chunk_index"],
                relevance_score=c["relevance_score"],
            )
            for c in similar_chunks
        ],
        query=request.query,
    )


# ─── Conversation Management ────────────────────────────────────


@router.get("/conversations", response_model=ConversationListResponse)
async def list_conversations():
    """List all conversations, most recent first."""
    conversations = await db.get_conversations()
    return ConversationListResponse(
        conversations=[
            ConversationResponse(
                id=c["id"],
                title=c["title"],
                created_at=c["created_at"],
                updated_at=c["updated_at"],
                message_count=c.get("message_count", 0),
            )
            for c in conversations
        ]
    )


@router.delete("/conversations/{conv_id}", response_model=ConversationDeleteResponse)
async def delete_conversation(conv_id: str):
    """Delete a conversation and all its messages."""
    conv = await db.get_conversation(conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    deleted = await db.delete_conversation(conv_id)
    return ConversationDeleteResponse(
        id=conv_id,
        deleted=deleted,
        message=f"Deleted conversation '{conv['title']}'",
    )


@router.get("/conversations/{conv_id}/messages")
async def get_conversation_messages(conv_id: str, limit: int = 100):
    """Get messages for a conversation."""
    conv = await db.get_conversation(conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    messages = await db.get_conversation_messages(conv_id, limit=limit)
    return {"conversation_id": conv_id, "messages": messages}
