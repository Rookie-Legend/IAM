"""
PHASE 4 — Embeddings
Converts text chunks into vector embeddings using a lightweight local model.
We use `sentence-transformers` (paraphrase-MiniLM-L6-v2) — it is fast, small,
and runs entirely in-process without any external API call.
Embeddings are stored in MongoDB as lists of floats.
"""
import asyncio
from functools import lru_cache


@lru_cache(maxsize=1)
def _get_model():
    """Load the embedding model once and cache it."""
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer("paraphrase-MiniLM-L6-v2")


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Return a list of embedding vectors, one per text."""
    model = _get_model()
    embeddings = model.encode(texts, show_progress_bar=False, convert_to_numpy=True)
    return [e.tolist() for e in embeddings]


def embed_single(text: str) -> list[float]:
    """Return a single embedding vector for a query string."""
    model = _get_model()
    return model.encode(text, convert_to_numpy=True).tolist()


async def index_logs_to_db(db, chunks: list[str]) -> int:
    """
    Embed all chunks and upsert them into the `rag_chunks` collection.
    Returns the number of chunks indexed.
    """
    if not chunks:
        return 0

    # Run embedding in a thread (CPU-bound)
    embeddings = await asyncio.to_thread(embed_texts, chunks)

    # Clear the old index and re-insert (simple full refresh approach)
    await db["rag_chunks"].delete_many({})
    docs = [
        {"text": chunk, "embedding": emb}
        for chunk, emb in zip(chunks, embeddings)
    ]
    await db["rag_chunks"].insert_many(docs)
    return len(docs)
