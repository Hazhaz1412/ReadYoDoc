"""Chat, query, and conversation management API endpoints with SSE streaming."""

import json
import logging
import re
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
from app.services import embedding_service, vector_store, llm_service, settings_service, memory_service
from app.database import db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["Chat"])


def _looks_like_vietnamese(text: str) -> bool:
    """Heuristic language check for short UX responses."""
    normalized = text.lower()
    vietnamese_markers = [
        "xin chao",
        "xin chào",
        "toi",
        "tôi",
        "ban",
        "bạn",
        "giup",
        "giúp",
        "duoc gi",
        "được gì",
        "the nao",
        "thế nào",
        "tai lieu",
        "tài liệu",
    ]
    return any(marker in normalized for marker in vietnamese_markers)


def _normalize_query(text: str) -> str:
    """Normalize a user query for lightweight intent detection."""
    lowered = text.lower().strip()
    return re.sub(r"\s+", " ", lowered)


def _direct_assistant_reply(query: str) -> str | None:
    """Return a direct non-RAG reply for greetings and capability questions."""
    normalized = _normalize_query(query)
    is_vi = _looks_like_vietnamese(query)

    greeting_patterns = [
        r"^(hi|hello|hey|good morning|good afternoon|good evening)\b",
        r"^(xin chào|chào|hello|hi)\b",
    ]
    capability_markers = [
        "ban lam duoc gi",
        "bạn làm được gì",
        "ban co the lam gi",
        "bạn có thể làm gì",
        "toi co the lam gi voi ban",
        "tôi có thể làm gì với bạn",
        "what can you do",
        "how can you help",
        "who are you",
    ]

    if any(re.search(pattern, normalized) for pattern in greeting_patterns) or any(
        marker in normalized for marker in capability_markers
    ):
        if is_vi:
            return (
                "Xin chào! Tôi có thể giúp bạn làm việc với kho tài liệu đã tải lên.\n\n"
                "- Tóm tắt tài liệu\n"
                "- Trả lời câu hỏi dựa trên nội dung tài liệu\n"
                "- So sánh, tìm mâu thuẫn, trích ý chính\n"
                "- Chỉ ra nguồn tài liệu liên quan cho từng câu trả lời\n\n"
                "Nếu bạn muốn, hãy hỏi trực tiếp về nội dung tài liệu, ví dụ: "
                "`Tóm tắt tài liệu này`, `Tài liệu nói gì về microservices?`, hoặc "
                "`Có mâu thuẫn nào giữa các tài liệu không?`"
            )

        return (
            "Hello! I can help you work with the documents you uploaded.\n\n"
            "- Summarize documents\n"
            "- Answer questions grounded in the documents\n"
            "- Compare documents and find inconsistencies\n"
            "- Point to relevant source documents for each answer\n\n"
            "Try asking something like: `Summarize this document`, "
            "`What does the document say about microservices?`, or "
            "`Are there contradictions across these documents?`"
        )

    return None


def _stream_single_message(conversation_id: str, text: str) -> StreamingResponse:
    """Build an SSE response for direct assistant replies."""

    async def event_stream():
        yield f"data: {json.dumps({'type': 'meta', 'data': {'conversation_id': conversation_id}})}\n\n"
        yield f"data: {json.dumps({'type': 'sources', 'data': []})}\n\n"
        yield f"data: {json.dumps({'type': 'token', 'data': text})}\n\n"
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


@router.post("/chat")
async def chat(request: ChatRequest):
    """Ask a question and get a streaming answer based on uploaded documents.

    Returns Server-Sent Events (SSE) with:
    - type=meta: Conversation metadata (sent first)
    - type=sources: Source citations
    - type=token: Individual answer tokens
    - type=done: Signal that generation is complete
    """
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

    # Handle greetings / assistant capability questions outside RAG.
    direct_reply = _direct_assistant_reply(request.query)
    if direct_reply:
        await db.insert_chat_message(conversation_id, "assistant", direct_reply)
        return _stream_single_message(conversation_id, direct_reply)

    # Check if we have any documents
    if vector_store.get_total_chunks() == 0:
        raise HTTPException(
            status_code=400,
            detail="No documents uploaded yet. Please upload documents first.",
        )

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

    best_score = max(chunk["relevance_score"] for chunk in similar_chunks)
    if best_score < settings.MIN_RELEVANCE_SCORE:
        raise HTTPException(
            status_code=404,
            detail=(
                "The question does not appear to match the uploaded documents closely enough. "
                "Try asking about the document content more specifically."
            ),
        )

    # Load personalization memories if enabled
    personalization_on = settings_service.get("PERSONALIZATION_ENABLED")
    memories = []
    if personalization_on:
        memories = await db.get_active_memories()

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
            memories=memories if personalization_on else None,
        ):
            full_response.append(token)
            yield f"data: {json.dumps({'type': 'token', 'data': token})}\n\n"

        # Collect full text and process memories
        assistant_text = "".join(full_response)

        # Extract and save memories from response
        if personalization_on and assistant_text:
            clean_text, new_memories = memory_service.extract_memories_from_response(assistant_text)
            existing = await db.get_all_memories()

            saved_memories = []
            for mem_content in new_memories:
                if not memory_service.is_duplicate_memory(mem_content, existing):
                    mem_id = await db.insert_memory(mem_content, source="auto")
                    if mem_id:
                        saved_memories.append(mem_content)
                        logger.info(f"🧠 Memory saved: {mem_content[:80]}")

            # Send memory saved events to frontend
            for mem in saved_memories:
                yield f"data: {json.dumps({'type': 'memory_saved', 'data': mem})}\n\n"

            # Save the clean text (without memory tags) to DB
            if clean_text:
                await db.insert_chat_message(conversation_id, "assistant", clean_text)
        elif assistant_text:
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
