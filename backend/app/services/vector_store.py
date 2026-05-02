"""Vector store service — ChromaDB operations for storing and querying embeddings."""

import os
import chromadb
import logging
from pathlib import Path
from app.config import settings

logger = logging.getLogger(__name__)

# Persistent ChromaDB client (initialized once)
_chroma_client: chromadb.ClientAPI | None = None
_collection: chromadb.Collection | None = None


def _get_client() -> chromadb.ClientAPI:
    """Get or create the ChromaDB persistent client."""
    global _chroma_client
    if _chroma_client is None:
        chroma_host = os.getenv("CHROMA_HOST")
        if chroma_host:
            chroma_port = int(os.getenv("CHROMA_PORT", "8000"))
            _chroma_client = chromadb.HttpClient(host=chroma_host, port=chroma_port)
            logger.info(f"ChromaDB connected via HTTP to {chroma_host}:{chroma_port}")
        else:
            db_path = Path(settings.CHROMA_DB_PATH).resolve()
            db_path.mkdir(parents=True, exist_ok=True)
            _chroma_client = chromadb.PersistentClient(path=str(db_path))
            logger.info(f"ChromaDB initialized locally at {db_path}")
    return _chroma_client


def get_collection() -> chromadb.Collection:
    """Get or create the default document collection."""
    global _collection
    if _collection is None:
        client = _get_client()
        _collection = client.get_or_create_collection(
            name=settings.CHROMA_COLLECTION,
            metadata={"hnsw:space": "cosine"},  # cosine similarity
        )
        logger.info(
            f"Collection '{settings.CHROMA_COLLECTION}' ready "
            f"({_collection.count()} existing chunks)"
        )
    return _collection


def add_chunks(
    doc_id: str,
    chunks: list[dict],
    embeddings: list[list[float]],
) -> int:
    """Add document chunks to the vector store.

    Args:
        doc_id: The document ID (used to group chunks for deletion).
        chunks: List of chunk dicts with content, source, page, chunk_index.
        embeddings: Corresponding embedding vectors.

    Returns:
        Number of chunks added.
    """
    collection = get_collection()

    ids = [f"{doc_id}_chunk_{c['chunk_index']}" for c in chunks]
    documents = [c["content"] for c in chunks]
    metadatas = [
        {
            "doc_id": doc_id,
            "source": c["source"],
            "page": c.get("page") or -1,  # ChromaDB doesn't support None in metadata
            "chunk_index": c["chunk_index"],
        }
        for c in chunks
    ]

    # ChromaDB handles batching internally, but we chunk in groups of 100
    # to avoid memory issues with very large documents
    batch_size = 100
    added = 0
    for i in range(0, len(ids), batch_size):
        end = min(i + batch_size, len(ids))
        collection.add(
            ids=ids[i:end],
            documents=documents[i:end],
            embeddings=embeddings[i:end],
            metadatas=metadatas[i:end],
        )
        added += end - i

    logger.info(f"Added {added} chunks for document {doc_id}")
    return added


def query_similar(
    query_embedding: list[float],
    top_k: int = 5,
) -> list[dict]:
    """Find the most similar chunks to a query embedding.

    Args:
        query_embedding: The query vector.
        top_k: Number of results to return.

    Returns:
        List of dicts with content, source, page, chunk_index, relevance_score.
    """
    collection = get_collection()

    if collection.count() == 0:
        return []

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=min(top_k, collection.count()),
        include=["documents", "metadatas", "distances"],
    )

    chunks = []
    for i in range(len(results["ids"][0])):
        # ChromaDB returns cosine distance; convert to similarity score
        distance = results["distances"][0][i]
        similarity = 1.0 - distance  # cosine similarity = 1 - cosine distance

        chunks.append({
            "content": results["documents"][0][i],
            "source_file": results["metadatas"][0][i].get("source", "unknown"),
            "page": results["metadatas"][0][i].get("page"),
            "chunk_index": results["metadatas"][0][i].get("chunk_index", 0),
            "relevance_score": round(similarity, 4),
        })

    return chunks


def delete_document_chunks(doc_id: str) -> int:
    """Delete all chunks belonging to a document.

    Args:
        doc_id: The document ID.

    Returns:
        Number of chunks deleted.
    """
    collection = get_collection()

    # Get all chunk IDs for this document
    results = collection.get(
        where={"doc_id": doc_id},
        include=[],
    )

    if not results["ids"]:
        return 0

    count = len(results["ids"])
    collection.delete(ids=results["ids"])
    logger.info(f"Deleted {count} chunks for document {doc_id}")
    return count


def get_total_chunks() -> int:
    """Get total number of chunks in the collection."""
    return get_collection().count()
