"""LLM service — chat/answer generation via Ollama streaming API."""

import httpx
import json
import logging
from typing import AsyncGenerator
from app.config import settings

logger = logging.getLogger(__name__)

# Longer timeout for LLM generation (can be slow for large context)
_client = httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=10.0))

SYSTEM_PROMPT = """You are a helpful AI assistant that answers questions based ONLY on the provided context from the user's documents.

Rules:
1. ONLY use information from the provided context to answer.
2. If the context doesn't contain enough information to answer the question, clearly say: "I don't have enough information in the uploaded documents to answer this question."
3. Always mention which source document(s) you are referencing in your answer.
4. Be concise but thorough.
5. If the user asks in Vietnamese, respond in Vietnamese. If they ask in English, respond in English.
6. Format your answer with markdown when appropriate (bullet points, bold, code blocks).
7. You have access to the conversation history. Use it to understand follow-up questions, pronouns like "it", "that", "this", and references to previous answers. Maintain context across the conversation."""


def _build_prompt(
    query: str,
    context_chunks: list[dict],
    history: list[dict] | None = None,
    use_thinking: bool = False,
) -> list[dict]:
    """Build the chat messages with retrieved context and conversation history.

    Args:
        query: User's question.
        context_chunks: Retrieved document chunks with metadata.
        history: Previous conversation messages (role + content dicts).
        use_thinking: Whether to enable qwen3.5 thinking mode.

    Returns:
        List of message dicts for the Ollama chat API.
    """
    # Format context with source citations
    context_parts = []
    for i, chunk in enumerate(context_chunks, 1):
        source = chunk.get("source_file", "unknown")
        page = chunk.get("page")
        page_str = f", Page {page}" if page and page > 0 else ""
        score = chunk.get("relevance_score", 0)
        context_parts.append(
            f"[Source {i}: {source}{page_str} | Relevance: {score:.0%}]\n{chunk['content']}"
        )

    context_text = "\n\n---\n\n".join(context_parts)

    user_message = f"""Context from uploaded documents:
---
{context_text}
---

User question: {query}"""

    # Append /no_think to disable thinking mode if not wanted (qwen3.5 feature)
    if not use_thinking:
        user_message += " /no_think"

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    # Inject conversation history (oldest first) between system and current question
    if history:
        for msg in history:
            messages.append({"role": msg["role"], "content": msg["content"]})

    messages.append({"role": "user", "content": user_message})

    return messages


async def generate_answer_stream(
    query: str,
    context_chunks: list[dict],
    history: list[dict] | None = None,
    use_thinking: bool = False,
) -> AsyncGenerator[str, None]:
    """Stream answer tokens from the LLM.

    Args:
        query: User's question.
        context_chunks: Retrieved context chunks.
        history: Previous conversation messages for memory.
        use_thinking: Enable thinking mode for complex questions.

    Yields:
        Individual text tokens as they're generated.
    """
    messages = _build_prompt(query, context_chunks, history, use_thinking)

    url = f"{settings.OLLAMA_BASE_URL}/api/chat"
    payload = {
        "model": settings.LLM_MODEL,
        "messages": messages,
        "stream": True,
        "options": {
            "temperature": settings.LLM_TEMPERATURE,
        },
    }

    try:
        async with _client.stream("POST", url, json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                    # Skip thinking tokens (between <think> tags)
                    message = data.get("message", {})
                    content = message.get("content", "")
                    if content:
                        yield content

                    # Check if generation is done
                    if data.get("done", False):
                        break
                except json.JSONDecodeError:
                    continue

    except httpx.ConnectError:
        yield f"\n\n⚠️ Error: Cannot connect to Ollama server at {settings.OLLAMA_BASE_URL}"
    except httpx.HTTPStatusError as e:
        yield f"\n\n⚠️ Error: LLM returned status {e.response.status_code}"


async def generate_answer(
    query: str,
    context_chunks: list[dict],
    history: list[dict] | None = None,
    use_thinking: bool = False,
) -> str:
    """Generate a complete answer (non-streaming).

    Args:
        query: User's question.
        context_chunks: Retrieved context chunks.
        history: Previous conversation messages for memory.
        use_thinking: Enable thinking mode.

    Returns:
        The complete answer string.
    """
    parts = []
    async for token in generate_answer_stream(query, context_chunks, history, use_thinking):
        parts.append(token)
    return "".join(parts)


async def check_llm_connection() -> bool:
    """Check if the LLM model is available on the Ollama server."""
    try:
        url = f"{settings.OLLAMA_BASE_URL}/api/tags"
        response = await _client.get(url)
        response.raise_for_status()
        models = response.json().get("models", [])
        model_names = [m["name"] for m in models]
        return any(settings.LLM_MODEL in name for name in model_names)
    except Exception:
        return False
