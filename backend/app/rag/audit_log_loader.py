"""
PHASE 3 — Audit Log Loader
Reads access request logs from MongoDB, converts each row into readable text,
chunks them, and prepares for embedding.
"""
from datetime import datetime


def log_to_text(log: dict) -> str:
    """Convert a single audit log document into a natural-language text snippet."""
    parts = []

    user_id = log.get("user_id") or log.get("target_user", "unknown")
    action = (log.get("action") or "unknown").upper()
    details = log.get("details") or ""
    timestamp = log.get("timestamp")
    target = log.get("target_user") or ""

    # Format timestamp
    ts_str = ""
    if isinstance(timestamp, datetime):
        ts_str = timestamp.strftime("%Y-%m-%d %H:%M:%S")
    elif isinstance(timestamp, str):
        ts_str = timestamp

    parts.append(f"User {user_id}")

    if ts_str:
        parts.append(f"at {ts_str}")

    # Map action to human-readable description
    action_map = {
        "JOINER": "was onboarded into the system",
        "MOVER": "was transferred to a new department",
        "LEAVER": "was offboarded and all access was revoked",
        "DISABLE_USER": "had their account disabled",
        "DISABLE": "had their account disabled",
        "REINSTATE": "was reinstated and account re-enabled",
        "GRANT": "was granted access",
        "DENY": "was denied access",
        "REVOKE": "had access revoked",
        "ESCALATE": "triggered an escalation",
        "MFA_CHALLENGE": "triggered an MFA challenge",
        "LOGIN": "logged in",
        "LOGOUT": "logged out",
    }
    action_desc = action_map.get(action, f"performed action: {action}")
    parts.append(action_desc)

    if target and target != user_id:
        parts.append(f"(target: {target})")

    text = " ".join(parts) + "."

    # Append details if present
    if details:
        text += f" Details: {details}"

    return text.strip()


async def load_logs_from_db(db, limit: int = 500) -> list[str]:
    """
    Fetch audit logs from MongoDB and convert each to a text snippet.
    Returns a list of text strings, one per log entry.
    """
    cursor = db["audit_logs"].find().sort("timestamp", -1).limit(limit)
    logs = await cursor.to_list(length=limit)
    texts = []
    for log in logs:
        try:
            text = log_to_text(log)
            if text:
                texts.append(text)
        except Exception:
            continue
    return texts


def chunk_texts(texts: list[str], chunk_size: int = 300, overlap: int = 50) -> list[str]:
    """
    Combine all log texts into one big string then chunk it into overlapping segments.
    Each segment is a chunk to be embedded.
    """
    combined = "\n\n".join(texts)
    chunks = []
    start = 0
    while start < len(combined):
        end = start + chunk_size
        chunk = combined[start:end]
        if chunk.strip():
            chunks.append(chunk.strip())
        start += chunk_size - overlap
    return chunks
