"""Memory service — extract, deduplicate, and format user memories."""

import re
import logging
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)

# Regex to find <memory_save>...</memory_save> tags in LLM responses
_MEMORY_TAG_RE = re.compile(
    r"<memory_save>(.*?)</memory_save>",
    re.DOTALL | re.IGNORECASE,
)

SIMILARITY_THRESHOLD = 0.7  # Skip saving if existing memory is ≥70% similar


def extract_memories_from_response(text: str) -> tuple[str, list[str]]:
    """Parse <memory_save> tags from LLM response.

    Returns:
        (clean_text, list_of_memory_strings)
        clean_text has the tags stripped out.
    """
    memories = [m.strip() for m in _MEMORY_TAG_RE.findall(text) if m.strip()]
    clean = _MEMORY_TAG_RE.sub("", text).strip()
    # Remove leftover blank lines from stripping
    clean = re.sub(r"\n{3,}", "\n\n", clean)
    return clean, memories


def is_duplicate_memory(new_content: str, existing_memories: list[dict]) -> bool:
    """Check if a new memory is too similar to any existing one."""
    new_lower = new_content.lower().strip()
    for mem in existing_memories:
        existing_lower = mem["content"].lower().strip()
        ratio = SequenceMatcher(None, new_lower, existing_lower).ratio()
        if ratio >= SIMILARITY_THRESHOLD:
            logger.info(
                f"Memory duplicate detected ({ratio:.0%}): "
                f"'{new_content[:60]}' ≈ '{mem['content'][:60]}'"
            )
            return True
    return False


def format_memories_for_prompt(memories: list[dict]) -> str:
    """Format a list of memory dicts into a text block for the system prompt."""
    if not memories:
        return ""

    lines = []
    for i, mem in enumerate(memories, 1):
        lines.append(f"  {i}. {mem['content']}")

    return "\n".join(lines)
