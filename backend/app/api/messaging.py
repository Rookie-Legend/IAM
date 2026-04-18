from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from datetime import datetime
from app.core.database import get_database
from app.api.dependencies import get_current_user
from app.models.user import UserInDB

router = APIRouter(prefix="/api/messaging", tags=["Messaging"])

ADMIN_ROLES = ["Security Admin", "System Administrator", "HR Manager", "admin"]


def make_conversation_id(uid1: str, uid2: str) -> str:
    """Deterministic conversation ID regardless of who initiates."""
    return "_".join(sorted([uid1, uid2]))


class SendMessageRequest(BaseModel):
    content: str


# ── List chattable users ──

@router.get("/users")
async def list_chattable_users(
    db=Depends(get_database),
    current_user: UserInDB = Depends(get_current_user)
):
    """Return all non-admin users except the current user."""
    cursor = db["users"].find(
        {
            "user_id": {"$ne": current_user.user_id},
            "role": {"$nin": ADMIN_ROLES},
            "disabled": {"$ne": True}
        },
        {"hashed_password": 0, "_id": 0}
    )
    users = await cursor.to_list(length=500)
    return [
        {
            "user_id": u.get("user_id"),
            "full_name": u.get("full_name", u.get("username", "Unknown")),
            "department": u.get("department", ""),
            "role": u.get("role", ""),
        }
        for u in users
    ]


# ── List conversations (last message + unread count) ──

@router.get("/conversations")
async def list_conversations(
    db=Depends(get_database),
    current_user: UserInDB = Depends(get_current_user)
):
    """Return all conversations the current user is a part of, with last message and unread count."""
    # Find all messages involving current user
    pipeline = [
        {
            "$match": {
                "$or": [
                    {"sender_id": current_user.user_id},
                    {"receiver_id": current_user.user_id}
                ]
            }
        },
        {"$sort": {"timestamp": -1}},
        {
            "$group": {
                "_id": "$conversation_id",
                "last_message": {"$first": "$content"},
                "last_timestamp": {"$first": "$timestamp"},
                "last_sender_id": {"$first": "$sender_id"},
                "unread_count": {
                    "$sum": {
                        "$cond": [
                            {
                                "$and": [
                                    {"$eq": ["$receiver_id", current_user.user_id]},
                                    {"$eq": ["$read", False]}
                                ]
                            },
                            1, 0
                        ]
                    }
                }
            }
        },
        {"$sort": {"last_timestamp": -1}}
    ]
    convos = await db["messages"].aggregate(pipeline).to_list(length=100)

    # Enrich with partner user info
    result = []
    for c in convos:
        conv_id = c["_id"]
        parts = conv_id.split("_") if conv_id else []
        partner_id = next((p for p in parts if p != current_user.user_id), None)
        if not partner_id:
            continue
        partner = await db["users"].find_one({"user_id": partner_id}, {"hashed_password": 0})
        ts = c.get("last_timestamp")
        result.append({
            "conversation_id": conv_id,
            "partner_id": partner_id,
            "partner_name": partner.get("full_name", partner_id) if partner else partner_id,
            "partner_department": partner.get("department", "") if partner else "",
            "last_message": c.get("last_message", ""),
            "last_timestamp": (ts.strftime('%Y-%m-%dT%H:%M:%S.') + f'{ts.microsecond:06d}'[:3] + 'Z') if ts else None,
            "unread_count": c.get("unread_count", 0),
        })
    return result


# ── Get messages in a conversation ──

@router.get("/conversations/{partner_id}/messages")
async def get_messages(
    partner_id: str,
    db=Depends(get_database),
    current_user: UserInDB = Depends(get_current_user)
):
    """Fetch all messages between current user and partner."""
    conv_id = make_conversation_id(current_user.user_id, partner_id)
    cursor = db["messages"].find(
        {"conversation_id": conv_id}
    ).sort("timestamp", 1)
    msgs = await cursor.to_list(length=1000)
    return [
        {
            "id": str(m["_id"]),
            "sender_id": m.get("sender_id"),
            "receiver_id": m.get("receiver_id"),
            "content": m.get("content", ""),
            "timestamp": (m["timestamp"].strftime('%Y-%m-%dT%H:%M:%S.') + f'{m["timestamp"].microsecond:06d}'[:3] + 'Z') if m.get("timestamp") else None,
            "read": m.get("read", False),
        }
        for m in msgs
    ]


# ── Send a message ──

@router.post("/conversations/{partner_id}/messages")
async def send_message(
    partner_id: str,
    body: SendMessageRequest,
    db=Depends(get_database),
    current_user: UserInDB = Depends(get_current_user)
):
    """Send a message to another user."""
    if not body.content.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    # Validate partner exists and is not admin
    partner = await db["users"].find_one({"user_id": partner_id})
    if not partner:
        raise HTTPException(status_code=404, detail="User not found")
    if partner.get("role") in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Cannot send messages to admins")

    conv_id = make_conversation_id(current_user.user_id, partner_id)
    msg = {
        "conversation_id": conv_id,
        "sender_id": current_user.user_id,
        "receiver_id": partner_id,
        "content": body.content.strip(),
        "timestamp": datetime.utcnow(),
        "read": False,
    }
    result = await db["messages"].insert_one(msg)
    return {
        "id": str(result.inserted_id),
        "sender_id": current_user.user_id,
        "receiver_id": partner_id,
        "content": msg["content"],
        "timestamp": msg["timestamp"].strftime('%Y-%m-%dT%H:%M:%S.') + f'{msg["timestamp"].microsecond:06d}'[:3] + 'Z',
        "read": False,
    }


# ── Mark messages as read ──

@router.post("/conversations/{partner_id}/read")
async def mark_read(
    partner_id: str,
    db=Depends(get_database),
    current_user: UserInDB = Depends(get_current_user)
):
    """Mark all messages from partner to current user as read."""
    conv_id = make_conversation_id(current_user.user_id, partner_id)
    await db["messages"].update_many(
        {
            "conversation_id": conv_id,
            "receiver_id": current_user.user_id,
            "read": False
        },
        {"$set": {"read": True}}
    )
    return {"status": "ok"}
