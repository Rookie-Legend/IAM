"""
PHASE 6 & 7 — RAG Chatbot Engine + Fraud Detection
Receives admin question, retrieves relevant logs via vector search,
detects fraud patterns from raw audit logs, and generates an
explanation-based answer using the Groq LLM.
"""
import asyncio
import json
from datetime import datetime, timedelta
from groq import Groq
from app.core.config import settings

from app.rag.audit_log_loader import load_logs_from_db, chunk_texts
from app.rag.embeddings import index_logs_to_db
from app.rag.vector_store import (
    search_similar_logs,
    retrieve_user_logs,
    retrieve_suspicious_logs,
)

_groq_client = None


def _get_groq() -> Groq:
    global _groq_client
    if _groq_client is None:
        _groq_client = Groq(api_key=settings.GROQ_API_KEY)
    return _groq_client


def _sync_llm_call(messages: list) -> str:
    """Synchronous Groq call — run via asyncio.to_thread."""
    client = _get_groq()
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=messages,
        temperature=0.2,
        max_tokens=1200,
    )
    return response.choices[0].message.content.strip()


# ─────────────────────────────────────────────
#  Index builder — called before each RAG chat
# ─────────────────────────────────────────────

async def refresh_rag_index(db) -> int:
    """
    Re-read audit logs from MongoDB, chunk them, embed them,
    and store in the rag_chunks collection. Returns chunk count.
    """
    texts = await load_logs_from_db(db, limit=1000)
    chunks = chunk_texts(texts, chunk_size=400, overlap=80)
    count = await index_logs_to_db(db, chunks)
    return count


# ─────────────────────────────────────────────
#  Fraud detection rules (raw audit logs)
# ─────────────────────────────────────────────

async def detect_fraud_patterns(db) -> list[dict]:
    """
    Scan the audit_logs collection for suspicious patterns and
    return a structured list of findings.
    """
    since = datetime.utcnow() - timedelta(hours=24)
    cursor = db["audit_logs"].find({"timestamp": {"$gte": since}})
    logs = await cursor.to_list(length=2000)

    deny_counts: dict[str, int] = {}
    escalate_counts: dict[str, int] = {}
    user_actions: dict[str, list] = {}

    for log in logs:
        uid = log.get("user_id") or log.get("target_user", "unknown")
        action = (log.get("action") or "").upper()

        if action in ("DENY",):
            deny_counts[uid] = deny_counts.get(uid, 0) + 1
        if action == "ESCALATE":
            escalate_counts[uid] = escalate_counts.get(uid, 0) + 1
        user_actions.setdefault(uid, []).append(action)

    findings = []

    for uid, count in deny_counts.items():
        if count >= 3:
            findings.append({
                "user": uid,
                "risk": "HIGH" if count >= 5 else "MEDIUM",
                "pattern": "multiple_denials",
                "description": f"{uid} was denied {count} times in the last 24 hours.",
            })

    for uid, count in escalate_counts.items():
        if count >= 2:
            findings.append({
                "user": uid,
                "risk": "HIGH",
                "pattern": "repeated_escalations",
                "description": f"{uid} triggered {count} escalations in the last 24 hours.",
            })

    # Check cumulative deny+escalate
    for uid, actions in user_actions.items():
        if actions.count("DENY") + actions.count("ESCALATE") >= 4:
            already = [f for f in findings if f["user"] == uid]
            if not already:
                findings.append({
                    "user": uid,
                    "risk": "HIGH",
                    "pattern": "anomalous_activity",
                    "description": (
                        f"{uid} performed {len(actions)} actions with "
                        f"{actions.count('DENY')} denials and "
                        f"{actions.count('ESCALATE')} escalations in 24 hours."
                    ),
                })

    return sorted(findings, key=lambda x: 0 if x["risk"] == "HIGH" else 1)


# ─────────────────────────────────────────────
#  Intent classifier for RAG questions
# ─────────────────────────────────────────────

_RAG_INTENTS = {
    "user_query": [
        "why was", "denied", "explain", "reason", "user u", "access for",
        "decision for", "logs for", "history of", "what happened to",
    ],
    "suspicious": [
        "suspicious", "fraud", "anomaly", "risky", "risk", "threat",
        "unusual", "alert", "who tried", "unauthorized", "privilege misuse",
    ],
    "general": [],
}


def _classify_rag_intent(query: str) -> tuple[str, str | None]:
    """Return (intent, user_id_if_any)."""
    q = query.lower()

    # Extract user id
    import re
    uid_match = re.search(r"\b([a-z]\d{3,5})\b", q)
    user_id = uid_match.group(1).upper() if uid_match else None

    # Also check for name-like patterns
    if not user_id:
        name_match = re.search(r"user\s+([a-zA-Z]+)", q)
        if name_match:
            user_id = name_match.group(1)

    for kw in _RAG_INTENTS["suspicious"]:
        if kw in q:
            return "suspicious", user_id

    for kw in _RAG_INTENTS["user_query"]:
        if kw in q:
            if user_id:
                return "user_query", user_id
            return "user_query", None

    return "general", user_id


# ─────────────────────────────────────────────
#  Main RAG answer function
# ─────────────────────────────────────────────

async def rag_answer(query: str, db) -> str:
    """
    Full RAG pipeline:
      1. Refresh log index (picks up latest audit logs)
      2. Classify intent
      3. Retrieve relevant chunks
      4. If suspicious intent → also run fraud pattern detection
      5. Call Groq LLM with retrieved context + question
      6. Return final answer
    """
    # Step 1: refresh the vector index
    await refresh_rag_index(db)

    # Step 2: classify intent
    intent, user_id = _classify_rag_intent(query)

    # Step 3: retrieve context chunks
    if intent == "user_query" and user_id:
        chunks = await retrieve_user_logs(user_id, db, top_k=10)
        if not chunks:
            chunks = await search_similar_logs(query, db, top_k=8)
    elif intent == "suspicious":
        chunks = await retrieve_suspicious_logs(db, top_k=12)
    else:
        chunks = await search_similar_logs(query, db, top_k=8)

    context = "\n\n".join(chunks) if chunks else "No relevant logs found."

    # Step 4: fraud analysis for suspicious queries
    fraud_summary = ""
    if intent == "suspicious":
        findings = await detect_fraud_patterns(db)
        if findings:
            lines = []
            for f in findings[:10]:
                lines.append(
                    f"- [{f['risk']}] {f['user']}: {f['description']} (pattern: {f['pattern']})"
                )
            fraud_summary = "\n\nFraud Detection Report (last 24h):\n" + "\n".join(lines)

    # Step 5: build prompt and call LLM
    system_prompt = (
        "You are an IAM Security Analyst AI. Answer admin questions based strictly on the provided audit log context.\n\n"
        "STRICT FORMATTING RULES:\n"
        "- Do NOT use any markdown symbols: no *, **, #, ##, ---, >, or similar.\n"
        "- Do NOT use emojis.\n"
        "- Use plain numbered lists (1. 2. 3.) or simple labels (Risk Level: HIGH) only.\n"
        "- Be concise and direct. Avoid filler phrases and long preambles.\n"
        "- Keep the total response under 300 words unless the question genuinely requires more detail.\n"
        "- Use formal English only.\n\n"
        "When answering:\n"
        "- State the key finding first (one sentence).\n"
        "- List only the most relevant evidence points (max 4).\n"
        "- End with a brief recommendation if applicable.\n"
        "- If the logs do not contain enough information, say so in one sentence."
    )

    user_prompt = f"""Admin Question: {query}

Relevant Audit Log Context:
{context}
{fraud_summary}

Please provide a detailed, explanation-based answer using the log context above.
If you detect fraud or suspicious behaviour, explain the indicators and recommend actions."""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    try:
        answer = await asyncio.to_thread(_sync_llm_call, messages)
        return answer
    except Exception as e:
        return f"RAG engine error: {str(e)}"
