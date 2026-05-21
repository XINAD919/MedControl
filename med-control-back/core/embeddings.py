"""
Embedding generation using Voyage AI voyage-3-lite (512-dim).
Used after OCR to index prescription chunks for RAG search.
"""

import os

from core.db import save_document_embedding

_voyage_client = None


def _get_voyage_client():
    global _voyage_client
    if _voyage_client is None:
        import voyageai
        _voyage_client = voyageai.Client(api_key=os.getenv("VOYAGE_API_KEY"))
    return _voyage_client


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    if not text.strip():
        return []

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start += chunk_size - overlap

    return chunks


def _embed(text: str) -> list[float]:
    """Generate a 512-dim embedding for a single text chunk via Voyage AI."""
    client = _get_voyage_client()
    result = client.embed([text], model="voyage-3-lite")
    return result.embeddings[0]


async def generate_and_save_embeddings(doc_id: str, user_id: str, text: str) -> int:
    """
    Chunk text, embed each chunk, and persist to document_embeddings.
    Returns number of chunks saved.
    """
    chunks = chunk_text(text)
    if not chunks:
        return 0

    for idx, chunk in enumerate(chunks):
        try:
            embedding = _embed(chunk)
        except Exception as e:
            print(f"[embeddings] Failed to embed chunk {idx} for doc {doc_id}: {e}")
            continue

        await save_document_embedding(
            document_id=doc_id,
            user_id=user_id,
            chunk_text=chunk,
            chunk_index=idx,
            embedding=embedding,
        )

    return len(chunks)
