"""Document service — orchestrates the full document ingestion pipeline."""

import logging
from pathlib import Path
from pypdf import PdfReader
from docx import Document as DocxDocument

from app.config import settings
from app.services import chunking_service, embedding_service, vector_store
from app.database import db

logger = logging.getLogger(__name__)


async def process_document(file_path: str, filename: str, doc_id: str) -> int:
    """Process a document through the full RAG ingestion pipeline.

    Pipeline: Parse → Chunk → Embed → Store in ChromaDB.

    Args:
        file_path: Path to the uploaded file on disk.
        filename: Original filename.
        doc_id: Document ID from the database.

    Returns:
        Number of chunks created.

    Raises:
        Exception: If any step fails (status is updated to 'error' in DB).
    """
    try:
        # Step 1: Parse document to extract text
        logger.info(f"[{doc_id}] Parsing: {filename}")
        file_ext = Path(filename).suffix.lower()
        pages = _parse_document(file_path, file_ext)

        if not pages:
            raise ValueError("No text content extracted from document")

        total_text = sum(len(p.get("text", "")) for p in pages)
        logger.info(f"[{doc_id}] Extracted {len(pages)} pages, {total_text} chars")

        # Step 2: Chunk text
        logger.info(f"[{doc_id}] Chunking text...")
        chunks = chunking_service.chunk_pages(pages, source=filename)

        if not chunks:
            raise ValueError("No chunks created from document text")

        logger.info(f"[{doc_id}] Created {len(chunks)} chunks")

        # Step 3: Generate embeddings
        logger.info(f"[{doc_id}] Generating embeddings...")
        texts = [c["content"] for c in chunks]

        # Batch in groups of 32 to avoid overwhelming Ollama
        all_embeddings = []
        batch_size = 32
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            batch_embeddings = await embedding_service.generate_embeddings(batch)
            all_embeddings.extend(batch_embeddings)
            logger.info(
                f"[{doc_id}] Embedded batch {i // batch_size + 1}/"
                f"{(len(texts) - 1) // batch_size + 1}"
            )

        # Step 4: Store in ChromaDB
        logger.info(f"[{doc_id}] Storing in vector database...")
        added = vector_store.add_chunks(doc_id, chunks, all_embeddings)

        # Step 5: Update status
        await db.update_document_status(doc_id, status="ready", chunk_count=added)
        logger.info(f"[{doc_id}] ✅ Document processed: {added} chunks stored")
        return added

    except Exception as e:
        logger.error(f"[{doc_id}] ❌ Processing failed: {e}")
        await db.update_document_status(
            doc_id, status="error", error_message=str(e)
        )
        raise


def _parse_document(file_path: str, file_ext: str) -> list[dict]:
    """Parse a document file into pages of text.

    Args:
        file_path: Path to the file.
        file_ext: File extension (e.g., '.pdf').

    Returns:
        List of dicts with keys: text, page_number.
    """
    if file_ext == ".pdf":
        return _parse_pdf(file_path)
    elif file_ext == ".docx":
        return _parse_docx(file_path)
    elif file_ext in (".txt", ".md"):
        return _parse_text(file_path)
    else:
        raise ValueError(f"Unsupported file type: {file_ext}")


def _parse_pdf(file_path: str) -> list[dict]:
    """Extract text from a PDF file, page by page."""
    reader = PdfReader(file_path)
    pages = []
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        if text.strip():
            pages.append({"text": text, "page_number": i + 1})
    return pages


def _parse_docx(file_path: str) -> list[dict]:
    """Extract text from a DOCX file."""
    doc = DocxDocument(file_path)
    full_text = "\n\n".join(
        paragraph.text for paragraph in doc.paragraphs if paragraph.text.strip()
    )
    if not full_text.strip():
        return []
    # DOCX doesn't have natural page breaks, treat as single page
    return [{"text": full_text, "page_number": None}]


def _parse_text(file_path: str) -> list[dict]:
    """Read a plain text or markdown file."""
    # Try UTF-8 first, fallback to latin-1
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            with open(file_path, "r", encoding=encoding) as f:
                text = f.read()
            if text.strip():
                return [{"text": text, "page_number": None}]
            return []
        except UnicodeDecodeError:
            continue
    return []
