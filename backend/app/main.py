"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.config import settings
from app.database import db
from app.models.schemas import HealthResponse
from app.api import documents, chat
from app.services import vector_store, llm_service, embedding_service

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown events."""
    # Startup
    logger.info("🚀 Starting RAG Application...")
    await db.init_db()
    logger.info("📦 Database initialized")

    # Initialize ChromaDB collection
    collection = vector_store.get_collection()
    logger.info(f"🗄️  ChromaDB ready ({collection.count()} chunks)")

    # Check Ollama connectivity
    llm_ok = await llm_service.check_llm_connection()
    embed_ok = await embedding_service.check_embedding_model()
    logger.info(f"🤖 LLM ({settings.LLM_MODEL}): {'✅' if llm_ok else '❌ NOT FOUND'}")
    logger.info(f"📐 Embedding ({settings.EMBEDDING_MODEL}): {'✅' if embed_ok else '❌ NOT FOUND'}")

    if not embed_ok:
        logger.warning(
            f"⚠️  Embedding model '{settings.EMBEDDING_MODEL}' not found! "
            f"Run: ollama pull {settings.EMBEDDING_MODEL}"
        )

    yield

    # Shutdown
    logger.info("👋 Shutting down RAG Application")


# Create FastAPI app
app = FastAPI(
    title="AI RAG — Document Assistant",
    description="Ask questions about your documents using private AI",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — allow frontend to connect
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routers
app.include_router(documents.router)
app.include_router(chat.router)


# Health check
@app.get("/api/health", response_model=HealthResponse, tags=["System"])
async def health_check():
    """Check system health and connectivity."""
    llm_ok = await llm_service.check_llm_connection()
    embed_ok = await embedding_service.check_embedding_model()
    doc_count = await db.get_document_count()

    return HealthResponse(
        status="healthy" if (llm_ok and embed_ok) else "degraded",
        ollama_connected=llm_ok and embed_ok,
        llm_model=settings.LLM_MODEL,
        embedding_model=settings.EMBEDDING_MODEL,
        documents_count=doc_count,
        chroma_collection=settings.CHROMA_COLLECTION,
    )


# Serve frontend static files — check container path first, then local dev path
FRONTEND_DIR = Path("/frontend")
if not FRONTEND_DIR.exists():
    FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"

if FRONTEND_DIR.exists():
    app.mount("/css", StaticFiles(directory=str(FRONTEND_DIR / "css")), name="css")
    app.mount("/js", StaticFiles(directory=str(FRONTEND_DIR / "js")), name="js")

    @app.get("/", include_in_schema=False)
    async def serve_frontend():
        """Serve the frontend SPA."""
        return FileResponse(str(FRONTEND_DIR / "index.html"))
