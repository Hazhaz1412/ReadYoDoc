import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.config import settings
from app.database import db
from app.models.schemas import HealthResponse, SettingsUpdate
from app.api import documents, chat, memory
from app.services import vector_store, llm_service, embedding_service, vision_service, settings_service
from app.services.realtime_service import redis_subscriber

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

    # Load dynamic settings
    await settings_service.load_settings()

    # Initialize ChromaDB collection
    collection = vector_store.get_collection()
    logger.info(f"🗄️  ChromaDB ready ({collection.count()} chunks)")

    # Check Ollama connectivity
    llm_ok = await llm_service.check_llm_connection()
    embed_ok = await embedding_service.check_embedding_model()
    vision_ok = await vision_service.check_vision_model()
    
    llm_model = settings_service.get("LLM_MODEL")
    emb_model = settings_service.get("EMBEDDING_MODEL")
    vis_model = settings_service.get("VISION_MODEL")
    vis_enabled = settings_service.get("VISION_ENABLED")
    
    logger.info(f"🤖 LLM ({llm_model}): {'✅' if llm_ok else '❌ NOT FOUND'}")
    logger.info(f"📐 Embedding ({emb_model}): {'✅' if embed_ok else '❌ NOT FOUND'}")
    logger.info(f"👁️  Vision ({vis_model}): {'✅' if vision_ok else '❌ NOT FOUND'} (enabled={vis_enabled})")

    if not embed_ok:
        logger.warning(
            f"⚠️  Embedding model '{emb_model}' not found! "
            f"Run: ollama pull {emb_model}"
        )

    if vis_enabled and not vision_ok:
        logger.warning(
            f"⚠️  Vision model '{vis_model}' not found! "
            f"Run: ollama pull {vis_model}"
        )

    # Start Redis Pub/Sub subscriber — forwards worker progress to WS clients
    # If Redis is unavailable the subscriber retries silently (see realtime_service)
    _redis_task = asyncio.create_task(redis_subscriber())
    logger.info("📡 Redis document-events subscriber started")

    yield

    # Shutdown — cancel the subscriber gracefully
    _redis_task.cancel()
    try:
        await _redis_task
    except asyncio.CancelledError:
        pass
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
app.include_router(memory.router)


# Health check
@app.get("/api/health", response_model=HealthResponse, tags=["System"])
async def health_check():
    """Check system health and connectivity."""
    vis_enabled = settings_service.get("VISION_ENABLED")
    llm_ok = await llm_service.check_llm_connection()
    embed_ok = await embedding_service.check_embedding_model()
    vision_ok = await vision_service.check_vision_model() if vis_enabled else False
    doc_count = await db.get_document_count()

    return HealthResponse(
        status="healthy" if (llm_ok and embed_ok) else "degraded",
        ollama_connected=llm_ok and embed_ok,
        llm_model=settings_service.get("LLM_MODEL"),
        embedding_model=settings_service.get("EMBEDDING_MODEL"),
        vision_model=settings_service.get("VISION_MODEL"),
        vision_enabled=vis_enabled,
        documents_count=doc_count,
        chroma_collection=settings.CHROMA_COLLECTION,
    )


@app.get("/api/settings", tags=["System"])
async def get_settings():
    """Get dynamic system settings."""
    return settings_service.get_all()


@app.post("/api/settings", tags=["System"])
async def update_settings(payload: SettingsUpdate):
    """Update dynamic system settings."""
    updates = payload.model_dump(exclude_unset=True)
    if updates:
        await settings_service.update_settings(updates)
    return {"status": "success", "settings": settings_service.get_all()}


# Serve built frontend assets — container path first, then local dev build output
FRONTEND_DIR = Path("/frontend")
if not FRONTEND_DIR.exists():
    FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"

if FRONTEND_DIR.exists():
    app_dir = FRONTEND_DIR / "_app"
    if app_dir.exists():
        app.mount("/_app", StaticFiles(directory=str(app_dir)), name="app-assets")

    @app.get("/", include_in_schema=False)
    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_frontend(full_path: str = ""):
        """Serve the built frontend SPA."""
        return FileResponse(str(FRONTEND_DIR / "index.html"))
