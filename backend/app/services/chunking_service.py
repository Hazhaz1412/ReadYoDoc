"""Text chunking service — splits documents into overlapping chunks."""

from langchain_text_splitters import RecursiveCharacterTextSplitter
from app.config import settings
from app.services import settings_service


def chunk_text(
    text: str,
    source: str = "unknown",
    page: int | None = None,
) -> list[dict]:
    """Split text into overlapping chunks with metadata.

    Args:
        text: The full text to split.
        source: Source filename for metadata.
        page: Optional page number for metadata.

    Returns:
        List of dicts with keys: content, source, page, chunk_index.
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings_service.get("CHUNK_SIZE"),
        chunk_overlap=settings_service.get("CHUNK_OVERLAP"),
        length_function=len,
        separators=["\n\n", "\n", ". ", ", ", " ", ""],
    )

    chunks = splitter.split_text(text)

    result = []
    for i, chunk_text in enumerate(chunks):
        result.append({
            "content": chunk_text.strip(),
            "source": source,
            "page": page,
            "chunk_index": i,
        })

    return result


def chunk_pages(
    pages: list[dict],
    source: str = "unknown",
) -> list[dict]:
    """Split multiple pages into chunks, preserving page numbers.

    Args:
        pages: List of dicts with keys: text, page_number.
        source: Source filename.

    Returns:
        List of chunk dicts with page metadata.
    """
    all_chunks = []
    global_index = 0

    for page_data in pages:
        text = page_data.get("text", "")
        page_num = page_data.get("page_number")

        if not text.strip():
            continue

        page_chunks = chunk_text(text, source=source, page=page_num)

        # Re-index globally across all pages
        for chunk in page_chunks:
            chunk["chunk_index"] = global_index
            global_index += 1

        all_chunks.extend(page_chunks)

    return all_chunks
