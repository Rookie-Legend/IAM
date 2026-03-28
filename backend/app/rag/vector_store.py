"""
PHASE 5 — Vector Store
Provides similarity search over stored embeddings using cosine similarity.
All vectors are stored in MongoDB as lists of floats. At query time we fetch
all vectors and compute cosine similarity in NumPy (fast enough at log scale).
"""
import asyncio
import numpy as np
from app.rag.embeddings import embed_single


def cosine_similarity(a: list[float], b: list[float]) -> float:
    va = np.array(a, dtype=np.float32)
    vb = np.array(b, dtype=np.float32)
    norm_a = np.linalg.norm(va)
    norm_b = np.linalg.norm(vb)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(va, vb) / (norm_a * norm_b))


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    return cosine_similarity(a, b)


async def search_similar_logs(query: str, db, top_k: int = 8) -> list[str]:
    """
    Embed the query, compare to all stored chunks, and return top_k most similar.
    """
    query_emb = await asyncio.to_thread(embed_single, query)
    cursor = db["rag_chunks"].find({}, {"text": 1, "embedding": 1, "_id": 0})
    chunks = await cursor.to_list(length=2000)

    if not chunks:
        return []

    scored = []
    for chunk in chunks:
        emb = chunk.get("embedding")
        if emb:
            score = _cosine_similarity(query_emb, emb)
            scored.append((score, chunk["text"]))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [text for _, text in scored[:top_k]]


async def retrieve_user_logs(user_id: str, db, top_k: int = 10) -> list[str]:
    """
    Return text chunks that mention a specific user ID.
    Falls back to similarity search if direct match is sparse.
    """
    cursor = db["rag_chunks"].find(
        {"text": {"$regex": user_id, "$options": "i"}},
        {"text": 1, "_id": 0}
    )
    direct = await cursor.to_list(length=top_k * 2)
    if direct:
        return [d["text"] for d in direct[:top_k]]
    # Fallback to vector search
    return await search_similar_logs(user_id, db, top_k)


async def retrieve_suspicious_logs(db, top_k: int = 12) -> list[str]:
    """
    Return chunks most related to suspicious / fraud-like activity.
    Uses a composite query that covers common fraud patterns.
    """
    fraud_keywords = (
        "denied access suspicious escalation high risk repeated attempts "
        "privilege misuse unknown location multiple denials policy violation "
        "fraud anomaly unauthorized"
    )
    return await search_similar_logs(fraud_keywords, db, top_k)


async def search_similar(query: str, db, collection_name: str, top_k: int = 8) -> list[str]:
    """
    Generic similarity search over any collection's embeddings.
    Embeds the query and returns top_k most similar texts.
    """
    query_emb = await asyncio.to_thread(embed_single, query)
    cursor = db[collection_name].find({}, {"text": 1, "embedding": 1, "_id": 0})
    chunks = await cursor.to_list(length=2000)

    if not chunks:
        return []

    scored = []
    for chunk in chunks:
        emb = chunk.get("embedding")
        if emb:
            score = _cosine_similarity(query_emb, emb)
            scored.append((score, chunk["text"]))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [text for _, text in scored[:top_k]]


async def search_similar_policies(query: str, db, top_k: int = 5) -> list[str]:
    """
    Search policies using vector similarity for semantic matching.
    """
    return await search_similar(query, db, "policy_chunks", top_k)
