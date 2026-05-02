"""LLM service — chat/answer generation via Ollama streaming API."""

import httpx
import json
import logging
from typing import AsyncGenerator
from app.config import settings
from app.services import settings_service

logger = logging.getLogger(__name__)

# Longer timeout for LLM generation (can be slow for large context)
_client = httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=10.0))

SYSTEM_PROMPT = """You are a helpful AI assistant for document Q&A.

Rules:
1. For document-content questions, answer using the provided context from the uploaded documents.
2. Do not invent facts that are not supported by the retrieved context.
3. If the retrieved context does not contain enough information to answer a document-content question, clearly say: "I don't have enough information in the uploaded documents to answer this question."
4. When you answer from the documents, mention which source document(s) you are relying on.
5. Be concise but thorough.
6. If the user asks in Vietnamese, respond in Vietnamese. If they ask in English, respond in English.
7. Format your answer with markdown when appropriate (bullet points, bold, code blocks).
8. You have access to the conversation history. Use it to understand follow-up questions, pronouns like "it", "that", "this", and references to previous answers. Maintain context across the conversation."""

MEMORY_INSTRUCTION = """
## Memory Detection
If the user explicitly asks you to remember, save, or note something about themselves (e.g. "nhớ rằng...", "lưu lại...", "remember that..."), OR if you detect a strong repeated preference pattern across the conversation, wrap the personalization fact in a special tag:
<memory_save>concise description of the preference or fact</memory_save>

Rules for memory:
- Only save genuinely useful personalization facts (response style, language preference, expertise level, personal context).
- Do NOT save conversation-specific or document-specific data.
- Do NOT save something already listed in the existing memories below.
- Keep each memory under 100 characters, in the same language the user used.
- Place the tag at the very end of your response, after your main answer.
- You can save multiple memories by using multiple tags."""


def _build_prompt(
    query: str,
    context_chunks: list[dict],
    history: list[dict] | None = None,
    use_thinking: bool = False,
    memories: list[dict] | None = None,
) -> list[dict]:
    """Build the chat messages with retrieved context and conversation history.

    Args:
        query: User's question.
        context_chunks: Retrieved document chunks with metadata.
        history: Previous conversation messages (role + content dicts).
        use_thinking: Whether to enable qwen3.5 thinking mode.
        memories: Active user memories for personalization.

    Returns:
        List of message dicts for the Ollama chat API.
    """
    from app.services.memory_service import format_memories_for_prompt

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

    # Build system prompt with optional personalization
    system_content = SYSTEM_PROMPT
    if memories:
        formatted = format_memories_for_prompt(memories)
        system_content += f"\n\n## Personalization\nYou know the following about this user. Use these to personalize your responses:\n{formatted}"
        system_content += MEMORY_INSTRUCTION
    else:
        system_content += MEMORY_INSTRUCTION

    messages = [{"role": "system", "content": system_content}]

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
    memories: list[dict] | None = None,
) -> AsyncGenerator[str, None]:
    """Stream answer tokens from the LLM.

    Args:
        query: User's question.
        context_chunks: Retrieved context chunks.
        history: Previous conversation messages for memory.
        use_thinking: Enable thinking mode for complex questions.
        memories: Active user memories for personalization.

    Yields:
        Individual text tokens as they're generated.
    """
    messages = _build_prompt(query, context_chunks, history, use_thinking, memories)

    url = f"{settings.OLLAMA_BASE_URL}/api/chat"
    payload = {
        "model": settings_service.get("LLM_MODEL"),
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
    memories: list[dict] | None = None,
) -> str:
    """Generate a complete answer (non-streaming).

    Args:
        query: User's question.
        context_chunks: Retrieved context chunks.
        history: Previous conversation messages for memory.
        use_thinking: Enable thinking mode.
        memories: Active user memories for personalization.

    Returns:
        The complete answer string.
    """
    parts = []
    async for token in generate_answer_stream(query, context_chunks, history, use_thinking, memories):
        parts.append(token)
    return "".join(parts)


async def check_llm_connection() -> bool:
    """Check if the LLM model is available on the Ollama server."""
    try:
        llm_model = settings_service.get("LLM_MODEL")
        url = f"{settings.OLLAMA_BASE_URL}/api/tags"
        response = await _client.get(url)
        response.raise_for_status()
        models = response.json().get("models", [])
        model_names = [m["name"] for m in models]
        return any(llm_model in name for name in model_names)
    except Exception:
        return False
