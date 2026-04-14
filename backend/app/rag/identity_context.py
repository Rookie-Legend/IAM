"""
Unified RAG - Identity Context
Fetches live user identity and current access state from MongoDB.
Returns a structured text context block for the LLM decision engine.
"""


async def fetch_identity_context(user_id: str, db) -> str:
    """
    Retrieve user identity info + current access state.
    Returns a formatted string for use as LLM context.
    """
    user = await db["users"].find_one({"user_id": user_id})
    if not user:
        return "IDENTITY CONTEXT:\n- Status: USER NOT FOUND"

    state = await db["access_states"].find_one({"user_id": user_id})
    vpn_access = state.get("vpn_access", []) if state else []
    resources = state.get("resources", []) if state else []

    status = await compute_user_status(db, user)

    lines = [
        "IDENTITY CONTEXT:",
        f"- User ID: {user_id}",
        f"- Name: {user.get('full_name', 'Unknown')}",
        f"- Department: {user.get('department', 'Unknown')}",
        f"- Role: {user.get('role', 'Unknown')}",
        f"- Status: {status}",
        f"- Current VPN Access: {', '.join(vpn_access) if vpn_access else 'none'}",
        f"- Current Resources: {', '.join(resources) if resources else 'none'}",
    ]
    return "\n".join(lines)
from app.services.user_status import compute_user_status
