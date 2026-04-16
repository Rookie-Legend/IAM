"""
Unified RAG - Audit Context
Fetches the user's audit history and finds similar access patterns via vector search.
Computes trust level (TRUSTED / MODERATE / RISKY) and returns a context block.

Also surfaces admin-action events (disable/reinstate/offboard) targeting this user
so the LLM knows when an account was recently disabled then reinstated.
"""
from datetime import datetime
from app.rag.vector_store import search_similar_logs

# Admin actions that affect account standing — stored with target_user field
_ADMIN_ACCOUNT_ACTIONS = {"disable_user", "reinstate_user", "leaver"}


async def fetch_audit_context(user_id: str, db, search_query: str = None) -> str:
    """
    Analyse the last 20 audit_logs entries for this user (trust level computation).
    Also checks for admin actions targeting this user (disable/reinstate/offboard).
    Performs vector-based semantic search on rag_chunks for similar past patterns.
    Returns a formatted string for use as LLM context.
    """
    # --- User's own chatbot/action logs ---
    logs = (
        await db["audit_logs"]
        .find({"user_id": user_id})
        .sort("timestamp", -1)
        .to_list(length=20)
    )

    total = len(logs)
    accepted = sum(1 for l in logs if l.get("decision") == "ACCEPT")
    escalated = sum(1 for l in logs if l.get("decision") == "ESCALATE")
    denied = sum(1 for l in logs if l.get("decision") == "DENY")

    if total == 0:
        trust_level = "TRUSTED"
        deny_rate_pct = 0
    else:
        deny_rate_pct = round((denied / total) * 100)
        if deny_rate_pct <= 20:
            trust_level = "TRUSTED"
        elif deny_rate_pct <= 50:
            trust_level = "MODERATE"
        else:
            trust_level = "RISKY"

    recent = [l for l in logs if l.get("action") not in _ADMIN_ACCOUNT_ACTIONS][:3]
    recent_lines = []
    for l in recent:
        ts = l.get("timestamp", "")
        date_str = str(ts)[:10] if ts else "unknown"
        resource = l.get("target_resource", l.get("target_user", "unknown"))
        decision = l.get("decision", l.get("action", "?"))
        recent_lines.append(f"    - {date_str}: {resource} -> {decision}")

    lines = [
        "AUDIT CONTEXT:",
        f"- Total Logged Events: {total}",
        f"- Accepted: {accepted} | Escalated: {escalated} | Denied: {denied}",
        f"- Denial Rate: {deny_rate_pct}%",
        f"- Trust Level: {trust_level}",
    ]
    if recent_lines:
        lines.append("- Recent Access Requests:")
        lines.extend(recent_lines)
    else:
        lines.append("- Recent Access Requests: none")

    # --- Admin-action events targeting this user (disable / reinstate / offboard) ---
    # These are logged under the admin's user_id with target_user = this user
    admin_events = (
        await db["audit_logs"]
        .find({"target_user": user_id, "action": {"$in": list(_ADMIN_ACCOUNT_ACTIONS)}})
        .sort("timestamp", -1)
        .to_list(length=10)
    )

    if admin_events:
        lines.append("- Account History (admin actions on this account):")
        for ev in admin_events[:5]:
            ts = ev.get("timestamp", "")
            date_str = str(ts)[:16] if ts else "unknown"
            action = ev.get("action", "?")
            lines.append(f"    - {date_str}: {action}")

        # Determine most recent account action
        latest_action = admin_events[0].get("action", "")
        if latest_action == "reinstate_user":
            lines.append(
                "- ACCOUNT_STATUS_FLAG: RECENTLY_REINSTATED — "
                "account was disabled then reinstated; all prior VPN access was revoked. "
                "New VPN requests MUST be ESCALATED to an admin, never auto-ACCEPTED."
            )
        elif latest_action in ("disable_user", "leaver"):
            lines.append(
                "- ACCOUNT_STATUS_FLAG: RECENTLY_DISABLED — "
                "account was disabled/offboarded by an admin. Deny all requests."
            )

    if search_query:
        similar_patterns = await search_similar_logs(search_query, db, top_k=5)
        if similar_patterns:
            lines.append("\n- Similar Past Access Patterns (vector search):")
            for i, pattern in enumerate(similar_patterns[:3], 1):
                lines.append(f"    {i}. {pattern[:200]}")

    return "\n".join(lines)


async def was_recently_reinstated(user_id: str, db) -> bool:
    """
    Returns True if the most recent admin account-action on this user was a reinstatement.
    Used by the decision engine to hard-force ESCALATE instead of ACCEPT.
    """
    event = await db["audit_logs"].find_one(
        {"target_user": user_id, "action": {"$in": list(_ADMIN_ACCOUNT_ACTIONS)}},
        sort=[("timestamp", -1)],
    )
    if event and event.get("action") == "reinstate_user":
        return True
    return False
