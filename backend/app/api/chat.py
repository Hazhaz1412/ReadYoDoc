"""Chat and query API endpoints with SSE streaming."""

import json
import logging
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.models.schemas import (
    ChatRequest,
    ChatResponse,
    SearchRequest,
    SearchResponse,
    SourceChunk,
)
from app.services import embedding_service, vector_store, llm_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/chat", tags=["Chat"])


@router.post("")
async def chat(request: ChatRequest):
    """Ask a question and get a streaming answer based on uploaded documents.

    Returns Server-Sent Events (SSE) with:
    - type=token: Individual answer tokens
    - type=sources: Source citations (sent first)
    - type=done: Signal that generation is complete
    """
    # Check if we have any documents
    if vector_store.get_total_chunks() == 0:
        raise HTTPException(
            status_code=400,
            detail="No documents uploaded yet. Please upload documents first.",
        )

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
        # Send sources first
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

        # Stream answer tokens
        async for token in llm_service.generate_answer_stream(
            request.query,
            similar_chunks,
            use_thinking=request.use_thinking,
        ):
            yield f"data: {json.dumps({'type': 'token', 'data': token})}\n\n"

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


@router.post("/search", response_model=SearchResponse)
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
