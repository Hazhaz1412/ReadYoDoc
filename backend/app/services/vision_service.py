"""Vision service — image description via Ollama multimodal API (qwen2.5-vl)."""

import base64
import httpx
import json
import logging
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)

# Longer timeout: vision models can be slow, especially on first load
_client = httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=15.0))

VISION_PROMPT = """You are analyzing an image extracted from a document.
Describe the content of this image in detail, including:
- Any text, labels, or captions visible
- Charts, graphs, tables, or diagrams and their data
- Photographs or illustrations and what they depict
- Any relevant numbers, dates, or key information

Be factual and concise. Output only the description, no preamble."""


async def describe_image(
    image_base64: str,
    context_hint: str = "",
) -> Optional[str]:
    """Send an image to the vision model and get a text description.

    Args:
        image_base64: Base64-encoded image data (PNG or JPEG).
        context_hint: Optional hint about the document context.

    Returns:
        Text description of the image, or None if processing fails.
    """
    if not settings.VISION_ENABLED:
        return None

    prompt = VISION_PROMPT
    if context_hint:
        prompt += f"\n\nDocument context: This image comes from '{context_hint}'."

    url = f"{settings.OLLAMA_BASE_URL}/api/chat"
    payload = {
        "model": settings.VISION_MODEL,
        "messages": [
            {
                "role": "user",
                "content": prompt,
                "images": [image_base64],
            }
        ],
        "stream": False,
        "options": {
            "temperature": 0.2,  # Low temp for factual descriptions
        },
    }

    try:
        response = await _client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
        content = data.get("message", {}).get("content", "")
        if content:
            logger.info(f"Vision: described image ({len(content)} chars)")
            return content.strip()
        return None

    except httpx.ConnectError:
        logger.error(f"Vision: cannot connect to Ollama at {settings.OLLAMA_BASE_URL}")
        return None
    except httpx.HTTPStatusError as e:
        logger.error(f"Vision: Ollama returned status {e.response.status_code}")
        return None
    except Exception as e:
        logger.error(f"Vision: unexpected error: {e}")
        return None


async def describe_images(
    images_base64: list[str],
    context_hint: str = "",
) -> list[Optional[str]]:
    """Describe multiple images sequentially.

    Sequential processing avoids overloading VRAM on the Ollama host.

    Args:
        images_base64: List of base64-encoded images.
        context_hint: Optional document context hint.

    Returns:
        List of descriptions (None for any that failed).
    """
    descriptions = []
    for i, img in enumerate(images_base64):
        logger.info(f"Vision: processing image {i + 1}/{len(images_base64)}")
        desc = await describe_image(img, context_hint=context_hint)
        descriptions.append(desc)
    return descriptions


async def check_vision_model() -> bool:
    """Check if the vision model is available on the Ollama server."""
    if not settings.VISION_ENABLED:
        return False
    try:
        url = f"{settings.OLLAMA_BASE_URL}/api/tags"
        response = await _client.get(url)
        response.raise_for_status()
        models = response.json().get("models", [])
        model_names = [m["name"] for m in models]
        return any(settings.VISION_MODEL in name for name in model_names)
    except Exception:
        return False
