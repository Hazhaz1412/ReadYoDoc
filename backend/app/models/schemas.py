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
    status_detail: str = ""
    progress: int = 0
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
    conversation_id: Optional[str] = Field(default=None, description="Conversation ID for memory continuity")
    memory_limit: int = Field(default=20, ge=0, le=100, description="Max messages to include as context history")


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


# ─── Conversation Schemas ───────────────────────────────────────

class ConversationResponse(BaseModel):
    """Response model for a single conversation."""
    id: str
    title: str
    created_at: str
    updated_at: str
    message_count: int = 0


class ConversationListResponse(BaseModel):
    """Response for listing conversations."""
    conversations: list[ConversationResponse]


class ConversationDeleteResponse(BaseModel):
    """Response after deleting a conversation."""
    id: str
    deleted: bool
    message: str


# ─── Health Schemas ─────────────────────────────────────────────

class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    ollama_connected: bool
    llm_model: str
    embedding_model: str
    vision_model: str
    vision_enabled: bool
    documents_count: int
    chroma_collection: str
