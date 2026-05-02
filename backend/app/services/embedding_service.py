"""Embedding service — generates vector embeddings via Ollama API."""

import httpx
import logging
from app.config import settings

logger = logging.getLogger(__name__)

# Reusable async client with longer timeout for embedding large batches
_client = httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0))


async def generate_embedding(text: str) -> list[float]:
    """Generate embedding for a single text string.

    Args:
        text: The text to embed.

    Returns:
        A list of floats representing the embedding vector.
    """
    embeddings = await generate_embeddings([text])
    return embeddings[0]


async def generate_embeddings(texts: list[str]) -> list[list[float]]:
    """Generate embeddings for a batch of texts.

    Args:
        texts: List of text strings to embed.

    Returns:
        List of embedding vectors.

    Raises:
        httpx.HTTPStatusError: If the Ollama API returns an error.
        ConnectionError: If unable to reach the Ollama server.
    """
    url = f"{settings.OLLAMA_BASE_URL}/api/embed"
    payload = {
        "model": settings.EMBEDDING_MODEL,
        "input": texts,
    }

    try:
        response = await _client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
        embeddings = data.get("embeddings", [])

        if len(embeddings) != len(texts):
            raise ValueError(
                f"Expected {len(texts)} embeddings, got {len(embeddings)}"
            )

        logger.info(f"Generated {len(embeddings)} embeddings (dim={len(embeddings[0])})")
        return embeddings

    except httpx.ConnectError:
        logger.error(f"Cannot connect to Ollama at {settings.OLLAMA_BASE_URL}")
        raise ConnectionError(
            f"Cannot connect to Ollama server at {settings.OLLAMA_BASE_URL}. "
            "Is it running?"
        )
    except httpx.HTTPStatusError as e:
        logger.error(f"Ollama embedding error: {e.response.status_code} - {e.response.text}")
        raise


async def check_embedding_model() -> bool:
    """Check if the embedding model is available on the Ollama server."""
    try:
        url = f"{settings.OLLAMA_BASE_URL}/api/tags"
        response = await _client.get(url)
        response.raise_for_status()
        models = response.json().get("models", [])
        model_names = [m["name"] for m in models]
        return any(settings.EMBEDDING_MODEL in name for name in model_names)
    except Exception:
        return False
