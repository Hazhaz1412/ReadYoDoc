"""Document service — orchestrates the full document ingestion pipeline."""

import base64
import io
import logging
from pathlib import Path
from pypdf import PdfReader
from docx import Document as DocxDocument
from PIL import Image

from app.config import settings
from app.services import settings_service
from app.services import chunking_service, embedding_service, vector_store
from app.services import vision_service
from app.database import db
from app.services.realtime_service import document_events, serialize_document

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
        await _update_progress(
            doc_id,
            status="processing",
            status_detail="Reading and parsing document",
            progress=10,
        )

        # Step 1: Parse document to extract text
        logger.info(f"[{doc_id}] Parsing: {filename}")
        file_ext = Path(filename).suffix.lower()
        pages = _parse_document(file_path, file_ext)

        if not pages:
            raise ValueError("No text content extracted from document")

        total_text = sum(len(p.get("text", "")) for p in pages)
        logger.info(f"[{doc_id}] Extracted {len(pages)} pages, {total_text} chars")

        # Step 2: Vision — analyze images if enabled
        if settings_service.get("VISION_ENABLED"):
            await _update_progress(
                doc_id,
                status="processing",
                status_detail="Analyzing images in document",
                progress=15,
            )
            pages = await _enrich_pages_with_vision(pages, filename, doc_id)

        # Step 3: Chunk text
        await _update_progress(
            doc_id,
            status="processing",
            status_detail=f"Chunking {len(pages)} parsed section(s)",
            progress=35,
        )
        logger.info(f"[{doc_id}] Chunking text...")
        chunks = chunking_service.chunk_pages(pages, source=filename)

        if not chunks:
            raise ValueError("No chunks created from document text")

        logger.info(f"[{doc_id}] Created {len(chunks)} chunks")

        # Step 4: Generate embeddings
        await _update_progress(
            doc_id,
            status="processing",
            status_detail=f"Generating embeddings for {len(chunks)} chunks",
            progress=55,
        )
        logger.info(f"[{doc_id}] Generating embeddings...")
        texts = [c["content"] for c in chunks]

        # Batch in groups of 32 to avoid overwhelming Ollama
        all_embeddings = []
        batch_size = 32
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            batch_embeddings = await embedding_service.generate_embeddings(batch)
            all_embeddings.extend(batch_embeddings)
            progress = 55 + int(((i + len(batch)) / len(texts)) * 25)
            await _update_progress(
                doc_id,
                status="processing",
                status_detail=(
                    f"Embedding batch {i // batch_size + 1}/"
                    f"{(len(texts) - 1) // batch_size + 1}"
                ),
                progress=min(progress, 80),
            )
            logger.info(
                f"[{doc_id}] Embedded batch {i // batch_size + 1}/"
                f"{(len(texts) - 1) // batch_size + 1}"
            )

        # Step 5: Store in ChromaDB
        await _update_progress(
            doc_id,
            status="processing",
            status_detail="Indexing chunks in vector store",
            progress=90,
        )
        logger.info(f"[{doc_id}] Storing in vector database...")
        added = vector_store.add_chunks(doc_id, chunks, all_embeddings)

        # Step 6: Update status
        await db.update_document_status(
            doc_id,
            status="ready",
            chunk_count=added,
            status_detail=f"Indexed successfully with {added} chunks",
            progress=100,
        )
        await _broadcast_document(doc_id, event_type="document.updated")
        logger.info(f"[{doc_id}] ✅ Document processed: {added} chunks stored")
        return added

    except Exception as e:
        logger.error(f"[{doc_id}] ❌ Processing failed: {e}")
        await db.update_document_status(
            doc_id,
            status="error",
            error_message=str(e),
            status_detail="Processing failed",
            progress=100,
        )
        await _broadcast_document(doc_id, event_type="document.updated")
        raise


def _parse_document(file_path: str, file_ext: str) -> list[dict]:
    """Parse a document file into pages of text.

    Args:
        file_path: Path to the file.
        file_ext: File extension (e.g., '.pdf').

    Returns:
        List of dicts with keys: text, page_number, images (optional).
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
    """Extract text and images from a PDF file, page by page."""
    reader = PdfReader(file_path)
    pages = []
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""

        # Extract images from this page
        images_b64 = []
        if settings_service.get("VISION_ENABLED"):
            try:
                for img_obj in page.images:
                    try:
                        img_data = img_obj.data
                        # Convert to PNG via Pillow for consistent format
                        pil_image = Image.open(io.BytesIO(img_data))
                        # Skip tiny images (likely decorative elements)
                        if pil_image.width < 50 or pil_image.height < 50:
                            continue
                        buf = io.BytesIO()
                        pil_image.convert("RGB").save(buf, format="PNG")
                        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
                        images_b64.append(b64)
                    except Exception as img_err:
                        logger.debug(f"Skipping unreadable image on page {i+1}: {img_err}")
            except Exception as e:
                logger.debug(f"Could not extract images from page {i+1}: {e}")

        if text.strip() or images_b64:
            pages.append({
                "text": text,
                "page_number": i + 1,
                "images": images_b64,
            })
    return pages


def _parse_docx(file_path: str) -> list[dict]:
    """Extract text and images from a DOCX file."""
    doc = DocxDocument(file_path)
    full_text = "\n\n".join(
        paragraph.text for paragraph in doc.paragraphs if paragraph.text.strip()
    )

    # Extract embedded images
    images_b64 = []
    if settings_service.get("VISION_ENABLED"):
        try:
            for rel in doc.part.rels.values():
                if "image" in rel.reltype:
                    try:
                        img_data = rel.target_part.blob
                        pil_image = Image.open(io.BytesIO(img_data))
                        # Skip tiny images
                        if pil_image.width < 50 or pil_image.height < 50:
                            continue
                        buf = io.BytesIO()
                        pil_image.convert("RGB").save(buf, format="PNG")
                        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
                        images_b64.append(b64)
                    except Exception as img_err:
                        logger.debug(f"Skipping unreadable DOCX image: {img_err}")
        except Exception as e:
            logger.debug(f"Could not extract images from DOCX: {e}")

    if not full_text.strip() and not images_b64:
        return []

    # DOCX doesn't have natural page breaks, treat as single page
    return [{"text": full_text, "page_number": None, "images": images_b64}]


def _parse_text(file_path: str) -> list[dict]:
    """Read a plain text or markdown file."""
    # Try UTF-8 first, fallback to latin-1
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            with open(file_path, "r", encoding=encoding) as f:
                text = f.read()
            if text.strip():
                return [{"text": text, "page_number": None, "images": []}]
            return []
        except UnicodeDecodeError:
            continue
    return []


async def _enrich_pages_with_vision(
    pages: list[dict],
    filename: str,
    doc_id: str,
) -> list[dict]:
    """Send page images to the vision model and append descriptions to text.

    Args:
        pages: Parsed pages with optional 'images' lists.
        filename: Source filename for context.
        doc_id: Document ID for progress updates.

    Returns:
        Pages with image descriptions appended to text.
    """
    total_images = sum(len(p.get("images", [])) for p in pages)
    if total_images == 0:
        logger.info(f"[{doc_id}] No images found in document")
        return pages

    logger.info(f"[{doc_id}] Found {total_images} images to analyze with vision model")
    processed = 0

    for page in pages:
        images = page.get("images", [])
        if not images:
            continue

        page_num = page.get("page_number", "?")
        descriptions = []

        for img_b64 in images:
            processed += 1
            await _update_progress(
                doc_id,
                status="processing",
                status_detail=f"Vision: analyzing image {processed}/{total_images} (page {page_num})",
                progress=15 + int((processed / total_images) * 15),
            )

            desc = await vision_service.describe_image(
                img_b64,
                context_hint=filename,
            )
            if desc:
                descriptions.append(desc)

        # Append image descriptions to page text
        if descriptions:
            img_text = "\n\n".join(
                f"[Image {i+1} Description: {desc}]"
                for i, desc in enumerate(descriptions)
            )
            page["text"] = (page.get("text", "") + "\n\n" + img_text).strip()

    logger.info(f"[{doc_id}] Vision processing complete: {processed} images analyzed")
    return pages


async def _update_progress(
    doc_id: str,
    status: str,
    status_detail: str,
    progress: int,
):
    """Persist and broadcast intermediate document progress."""
    doc = await db.get_document(doc_id)
    chunk_count = doc["chunk_count"] if doc else 0
    await db.update_document_status(
        doc_id,
        status=status,
        chunk_count=chunk_count,
        status_detail=status_detail,
        progress=progress,
    )
    await _broadcast_document(doc_id, event_type="document.updated")


async def _broadcast_document(doc_id: str, event_type: str):
    """Broadcast the latest document snapshot if available."""
    doc = await db.get_document(doc_id)
    if not doc:
        return
    await document_events.broadcast(
        {
            "type": event_type,
            "document": serialize_document(doc),
        }
    )
