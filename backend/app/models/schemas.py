"""Pydantic models for API request/response schemas."""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


# ─── Document Schemas ───────────────────────────────────────────

class DocumentResponse(BaseModel):
    """Response model for a single document."""
    id: str
    filename: str
    file_type: str
    file_size: int
    chunk_count: int
    status: str  # "processing", "ready", "error"
    upload_date: str
    error_message: Optional[str] = None


class DocumentListResponse(BaseModel):
    """Response model for listing documents."""
    documents: list[DocumentResponse]
    total: int


class DocumentDeleteResponse(BaseModel):
    """Response after deleting a document."""
    id: str
    deleted: bool
    message: str


# ─── Chat Schemas ───────────────────────────────────────────────

class ChatRequest(BaseModel):
    """Request model for chat/query."""
    query: str = Field(..., min_length=1, max_length=2000, description="The question to ask")
    top_k: int = Field(default=5, ge=1, le=20, description="Number of context chunks to retrieve")
    use_thinking: bool = Field(default=False, description="Enable qwen3.5 thinking mode for complex queries")


class SourceChunk(BaseModel):
    """A single source chunk from the vector database."""
    content: str
    source_file: str
    page: Optional[int] = None
    chunk_index: int
    relevance_score: float


class ChatResponse(BaseModel):
    """Full response for non-streaming chat."""
    answer: str
    sources: list[SourceChunk]
    query: str


class SearchRequest(BaseModel):
    """Request model for similarity search only (no LLM generation)."""
    query: str = Field(..., min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=20)


class SearchResponse(BaseModel):
    """Response for similarity search."""
    chunks: list[SourceChunk]
    query: str


# ─── Health Schemas ─────────────────────────────────────────────

class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    ollama_connected: bool
    llm_model: str
    embedding_model: str
    documents_count: int
    chroma_collection: str
