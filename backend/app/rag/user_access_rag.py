"""
User Access RAG - Vector-based RAG for user access decisions.
Uses sentence-transformers for semantic search over policies and access context.
Provides context for the IAM user chatbot access decision engine.
"""
import asyncio
from app.rag.embeddings import embed_single, embed_texts, index_docs_to_collection
from app.rag.vector_store import search_similar, search_similar_policies


async def refresh_policy_index(db) -> int:
    """
    Load all active policies, create text representations, embed and index them.
    Returns number of policies indexed.
    """
    policies = await db["policies"].find({"is_active": True}).to_list(length=100)
    
    if not policies:
        return 0

    policy_texts = []
    for policy in policies:
        rules = policy.get("rules", {})
        allowed_vpns = rules.get("allowed_vpns", rules.get("vpn_access", []))
        allowed_resources = rules.get("allowed_resources", rules.get("resources", []))
        mfa_required = rules.get("mfa_required", False)

        text_parts = [
            f"Policy: {policy.get('name', policy.get('_id', 'Unknown'))}",
            f"Type: {policy.get('type', 'access')}",
            f"Department: {policy.get('department', 'N/A')}",
            f"Description: {policy.get('description', 'N/A')}",
            f"Allowed VPNs: {', '.join(allowed_vpns) if allowed_vpns else 'none'}",
            f"Allowed Resources: {', '.join(allowed_resources) if allowed_resources else 'none'}",
            f"MFA Required: {'Yes' if mfa_required else 'No'}",
        ]
        policy_texts.append(" | ".join(text_parts))

    if not policy_texts:
        return 0

    count = await index_docs_to_collection(db, "policy_chunks", policy_texts)
    return count


async def user_access_rag_context(
    user_id: str,
    department: str,
    requested_resource: str,
    reason: str,
    db
) -> tuple[str, str, str]:
    """
    Build comprehensive RAG context for user access decisions using vector similarity.
    
    Returns (identity_context, policy_context, audit_context) strings.
    
    Uses sentence-transformers for:
    - Policy semantic search (finds relevant policies even with vague queries)
    - Access history similarity (finds similar past access patterns)
    """
    from app.rag.identity_context import fetch_identity_context
    from app.rag.policy_context import fetch_policy_context
    from app.rag.audit_context import fetch_audit_context

    identity_ctx = await fetch_identity_context(user_id, db)

    search_query = f"{requested_resource} {reason}" if reason else requested_resource
    policy_ctx = await fetch_policy_context(user_id, department, db, query=search_query)

    audit_ctx = await fetch_audit_context(user_id, db)

    return identity_ctx, policy_ctx, audit_ctx


async def get_similar_access_patterns(user_id: str, requested_resource: str, db, top_k: int = 5) -> list[str]:
    """
    Find similar past access requests using vector search.
    Helps predict outcome based on similar requests from other users.
    """
    query = f"access request for {requested_resource}"
    return await search_similar(query, db, "rag_chunks", top_k)
