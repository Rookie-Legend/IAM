"""
Audit RAG — fetches the user's recent audit log history from MongoDB.
Computes trust level (TRUSTED / MODERATE / RISKY) and returns a context block.
"""

from datetime import datetime


async def fetch_audit_context(user_id: str, db) -> str:
    """
    Analyse the last 20 audit_logs entries for this user.
    Returns a formatted string for use as LLM context.
    """
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

    # Trust level based on denial rate
    if total == 0:
        trust_level = "TRUSTED"   # New user — give benefit of the doubt
        deny_rate_pct = 0
    else:
        deny_rate_pct = round((denied / total) * 100)
        if deny_rate_pct <= 20:
            trust_level = "TRUSTED"
        elif deny_rate_pct <= 50:
            trust_level = "MODERATE"
        else:
            trust_level = "RISKY"

    # Build recent activity summary (last 3 chatbot access requests)
    recent = [l for l in logs if l.get("action") == "chatbot_access_request"][:3]
    recent_lines = []
    for l in recent:
        ts = l.get("timestamp", "")
        date_str = str(ts)[:10] if ts else "unknown"
        resource = l.get("target_resource", l.get("target_user", "unknown"))
        decision = l.get("decision", l.get("action", "?"))
        recent_lines.append(f"    • {date_str}: {resource} → {decision}")

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

    return "\n".join(lines)
