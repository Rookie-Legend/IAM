async def compute_user_status(db, user: dict) -> str:
    if not user:
        return "inactive"

    if user.get("disabled", False):
        return "disabled"

    active_session = await db["vpn_sessions"].find_one({
        "user_id": user.get("user_id"),
        "is_active": True,
        "connected_at": {"$ne": None}
    })
    return "active" if active_session else "inactive"


async def apply_user_status(db, user: dict) -> dict:
    if not user:
        return user

    updated = dict(user)
    updated["status"] = await compute_user_status(db, user)
    return updated
