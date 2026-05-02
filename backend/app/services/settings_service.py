"""Dynamic settings service to provide configuration across the app."""

import logging
from app.config import settings as env_settings
from app.database import db

logger = logging.getLogger(__name__)

# In-memory cache for fast synchronous or frequent reads
_cache = {}


async def load_settings():
    """Load all settings from DB into memory cache."""
    global _cache
    db_settings = await db.get_all_settings()
    
    # Defaults fallback to env vars if not set in DB
    _cache = {
        "LLM_MODEL": db_settings.get("LLM_MODEL", env_settings.LLM_MODEL),
        "EMBEDDING_MODEL": db_settings.get("EMBEDDING_MODEL", env_settings.EMBEDDING_MODEL),
        "VISION_MODEL": db_settings.get("VISION_MODEL", env_settings.VISION_MODEL),
        "VISION_ENABLED": db_settings.get("VISION_ENABLED", str(env_settings.VISION_ENABLED)).lower() == "true",
        "MEMORY_MAX_MESSAGES": int(db_settings.get("MEMORY_MAX_MESSAGES", env_settings.MEMORY_MAX_MESSAGES)),
        "CHUNK_SIZE": int(db_settings.get("CHUNK_SIZE", env_settings.CHUNK_SIZE)),
        "CHUNK_OVERLAP": int(db_settings.get("CHUNK_OVERLAP", env_settings.CHUNK_OVERLAP)),
    }
    logger.info("⚙️  System settings loaded from database")


def get(key: str):
    """Get a setting from the cache synchronously."""
    return _cache.get(key)


async def update_settings(updates: dict):
    """Update settings in DB and cache."""
    for key, value in updates.items():
        if key in _cache:
            # Type cast based on existing cache type
            if isinstance(_cache[key], bool):
                val_to_save = str(value).lower()
                _cache[key] = val_to_save == "true"
            elif isinstance(_cache[key], int):
                val_to_save = str(value)
                _cache[key] = int(value)
            else:
                val_to_save = str(value)
                _cache[key] = val_to_save
            
            await db.set_setting(key, val_to_save)
    
    logger.info(f"⚙️  Settings updated: {list(updates.keys())}")


def get_all() -> dict:
    """Get all settings from cache."""
    return _cache.copy()
