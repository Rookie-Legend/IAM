from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from bson import ObjectId

from app.api.dependencies import get_current_user
from app.core.database import get_database
from app.models.user import UserInDB

router = APIRouter(prefix="/api/messaging", tags=["Messaging"])

ADMIN_ROLES = ["Security Admin", "System Administrator", "HR Manager", "admin"]


def is_admin(user: UserInDB) -> bool:
    return user.role in ADMIN_ROLES


def make_conversation_id(uid1: str, uid2: str) -> str:
    """Deterministic conversation ID regardless of who initiates."""
    return "_".join(sorted([uid1, uid2]))


def make_group_conversation_id(department: str) -> str:
    return f"group:{department}"


def serialize_dt(value):
    if not value:
        return None
    return value.strftime("%Y-%m-%dT%H:%M:%S.") + f"{value.microsecond:06d}"[:3] + "Z"


def public_user(user: dict) -> dict:
    return {
        "user_id": user.get("user_id"),
        "full_name": user.get("full_name", user.get("username", "Unknown")),
        "department": user.get("department", ""),
        "role": user.get("role", ""),
    }


class SendMessageRequest(BaseModel):
    content: str


class UpdateMessageRequest(BaseModel):
    content: str


def serialize_message(message: dict, message_type: str = None, sender: dict = None) -> dict:
    conversation_type = message_type or message.get("conversation_type") or "direct"
    data = {
        "id": str(message["_id"]),
        "type": conversation_type,
        "conversation_id": message.get("conversation_id"),
        "sender_id": message.get("sender_id"),
        "content": message.get("content", ""),
        "timestamp": serialize_dt(message.get("timestamp")),
        "edited": message.get("edited", False),
        "edited_at": serialize_dt(message.get("edited_at")),
        "deleted": message.get("deleted", False),
        "deleted_at": serialize_dt(message.get("deleted_at")),
    }
    if conversation_type == "group":
        sender_info = public_user(sender) if sender else {}
        data.update({
            "sender_name": sender_info.get("full_name", message.get("sender_id")),
            "sender_department": sender_info.get("department", ""),
            "sender_role": sender_info.get("role", ""),
            "read_by": message.get("read_by", []),
        })
    else:
        data.update({
            "receiver_id": message.get("receiver_id"),
            "read": message.get("read", False),
        })
    return data


async def get_owned_message(db, message_id: str, current_user: UserInDB) -> dict:
    try:
        object_id = ObjectId(message_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Message not found")

    message = await db["messages"].find_one({"_id": object_id})
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")
    if message.get("sender_id") != current_user.user_id:
        raise HTTPException(status_code=403, detail="You can only modify your own messages")
    if message.get("deleted"):
        raise HTTPException(status_code=400, detail="Message has been deleted")
    return message


async def get_accessible_departments(db, current_user: UserInDB):
    if is_admin(current_user):
        departments = await db["users"].distinct("department", {"disabled": {"$ne": True}})
        return sorted(d for d in departments if d)
    return [current_user.department] if current_user.department else []


async def ensure_group_access(department: str, db, current_user: UserInDB):
    if not department:
        raise HTTPException(status_code=404, detail="Group not found")
    if not is_admin(current_user) and current_user.department != department:
        raise HTTPException(status_code=403, detail="You do not have access to this group")

    exists = await db["users"].find_one({"department": department, "disabled": {"$ne": True}})
    if not exists:
        raise HTTPException(status_code=404, detail="Group not found")


# ── List chattable users ──

@router.get("/users")
async def list_chattable_users(
    db=Depends(get_database),
    current_user: UserInDB = Depends(get_current_user),
):
    """Return all active users except the current user, including admins."""
    cursor = db["users"].find(
        {
            "user_id": {"$ne": current_user.user_id},
            "disabled": {"$ne": True},
        },
        {"hashed_password": 0, "_id": 0},
    )
    users = await cursor.to_list(length=500)
    return [public_user(u) for u in users]


# ── List conversations (direct + fixed department groups) ──

@router.get("/conversations")
async def list_conversations(
    db=Depends(get_database),
    current_user: UserInDB = Depends(get_current_user),
):
    """Return direct conversations and fixed department groups with unread counts."""
    direct_pipeline = [
        {
            "$match": {
                "conversation_type": {"$ne": "group"},
                "deleted": {"$ne": True},
                "$or": [
                    {"sender_id": current_user.user_id},
                    {"receiver_id": current_user.user_id},
                ],
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
                                    {"$eq": ["$read", False]},
                                ]
                            },
                            1,
                            0,
                        ]
                    }
                },
            }
        },
        {"$sort": {"last_timestamp": -1}},
    ]
    direct_convos = await db["messages"].aggregate(direct_pipeline).to_list(length=100)

    result = []
    for convo in direct_convos:
        conv_id = convo["_id"]
        parts = conv_id.split("_") if conv_id else []
        partner_id = next((p for p in parts if p != current_user.user_id), None)
        if not partner_id:
            continue
        partner = await db["users"].find_one({"user_id": partner_id}, {"hashed_password": 0})
        result.append({
            "type": "direct",
            "conversation_id": conv_id,
            "partner_id": partner_id,
            "partner_name": partner.get("full_name", partner_id) if partner else partner_id,
            "partner_department": partner.get("department", "") if partner else "",
            "partner_role": partner.get("role", "") if partner else "",
            "title": partner.get("full_name", partner_id) if partner else partner_id,
            "subtitle": f"{partner.get('department', '')} · {partner.get('role', '')}" if partner else "",
            "last_message": convo.get("last_message", ""),
            "last_timestamp": serialize_dt(convo.get("last_timestamp")),
            "unread_count": convo.get("unread_count", 0),
        })

    departments = await get_accessible_departments(db, current_user)
    for department in departments:
        conv_id = make_group_conversation_id(department)
        last_message = await db["messages"].find_one(
            {"conversation_type": "group", "conversation_id": conv_id, "deleted": {"$ne": True}},
            sort=[("timestamp", -1)],
        )
        unread_count = await db["messages"].count_documents({
            "conversation_type": "group",
            "conversation_id": conv_id,
            "deleted": {"$ne": True},
            "sender_id": {"$ne": current_user.user_id},
            "read_by": {"$ne": current_user.user_id},
        })
        member_count = await db["users"].count_documents({
            "department": department,
            "disabled": {"$ne": True},
        })
        sender_name = ""
        if last_message:
            sender = await db["users"].find_one({"user_id": last_message.get("sender_id")})
            sender_name = sender.get("full_name", last_message.get("sender_id", "")) if sender else last_message.get("sender_id", "")
        result.append({
            "type": "group",
            "conversation_id": conv_id,
            "department": department,
            "title": f"{department} Group",
            "subtitle": f"{member_count} member{'s' if member_count != 1 else ''}",
            "member_count": member_count,
            "last_message": last_message.get("content", "") if last_message else "",
            "last_sender_name": sender_name,
            "last_timestamp": serialize_dt(last_message.get("timestamp")) if last_message else None,
            "unread_count": unread_count,
        })

    return sorted(
        result,
        key=lambda c: (c.get("last_timestamp") is not None, c.get("last_timestamp") or "", c["type"] == "group"),
        reverse=True,
    )


# ── Direct messages ──

@router.get("/conversations/{partner_id}/messages")
async def get_messages(
    partner_id: str,
    db=Depends(get_database),
    current_user: UserInDB = Depends(get_current_user),
):
    """Fetch all messages between current user and partner."""
    conv_id = make_conversation_id(current_user.user_id, partner_id)
    cursor = db["messages"].find(
        {
            "conversation_type": {"$ne": "group"},
            "conversation_id": conv_id,
            "deleted": {"$ne": True},
        }
    ).sort("timestamp", 1)
    msgs = await cursor.to_list(length=1000)
    return [serialize_message(m, "direct") for m in msgs]


@router.post("/conversations/{partner_id}/messages")
async def send_message(
    partner_id: str,
    body: SendMessageRequest,
    db=Depends(get_database),
    current_user: UserInDB = Depends(get_current_user),
):
    """Send a direct message to another active user, including admins."""
    content = body.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    if partner_id == current_user.user_id:
        raise HTTPException(status_code=400, detail="Cannot message yourself")

    partner = await db["users"].find_one({"user_id": partner_id, "disabled": {"$ne": True}})
    if not partner:
        raise HTTPException(status_code=404, detail="User not found")

    conv_id = make_conversation_id(current_user.user_id, partner_id)
    msg = {
        "conversation_type": "direct",
        "conversation_id": conv_id,
        "sender_id": current_user.user_id,
        "receiver_id": partner_id,
        "content": content,
        "timestamp": datetime.utcnow(),
        "read": False,
        "edited": False,
        "deleted": False,
    }
    result = await db["messages"].insert_one(msg)
    msg["_id"] = result.inserted_id
    return serialize_message(msg, "direct")


@router.post("/conversations/{partner_id}/read")
async def mark_read(
    partner_id: str,
    db=Depends(get_database),
    current_user: UserInDB = Depends(get_current_user),
):
    """Mark all direct messages from partner to current user as read."""
    conv_id = make_conversation_id(current_user.user_id, partner_id)
    await db["messages"].update_many(
        {
            "conversation_type": {"$ne": "group"},
            "conversation_id": conv_id,
            "receiver_id": current_user.user_id,
            "read": False,
            "deleted": {"$ne": True},
        },
        {"$set": {"read": True}},
    )
    return {"status": "ok"}


# ── Fixed department group messages ──

@router.get("/groups/{department}/messages")
async def get_group_messages(
    department: str,
    db=Depends(get_database),
    current_user: UserInDB = Depends(get_current_user),
):
    """Fetch messages for a fixed department group."""
    await ensure_group_access(department, db, current_user)
    conv_id = make_group_conversation_id(department)
    cursor = db["messages"].find(
        {
            "conversation_type": "group",
            "conversation_id": conv_id,
            "deleted": {"$ne": True},
        }
    ).sort("timestamp", 1)
    msgs = await cursor.to_list(length=1000)

    sender_ids = list({m.get("sender_id") for m in msgs if m.get("sender_id")})
    senders = await db["users"].find(
        {"user_id": {"$in": sender_ids}},
        {"hashed_password": 0},
    ).to_list(length=500)
    sender_map = {u.get("user_id"): public_user(u) for u in senders}

    return [serialize_message(m, "group", sender_map.get(m.get("sender_id"))) for m in msgs]


@router.post("/groups/{department}/messages")
async def send_group_message(
    department: str,
    body: SendMessageRequest,
    db=Depends(get_database),
    current_user: UserInDB = Depends(get_current_user),
):
    """Send a message to a fixed department group."""
    await ensure_group_access(department, db, current_user)
    content = body.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    conv_id = make_group_conversation_id(department)
    msg = {
        "conversation_type": "group",
        "conversation_id": conv_id,
        "department": department,
        "sender_id": current_user.user_id,
        "content": content,
        "timestamp": datetime.utcnow(),
        "read_by": [current_user.user_id],
        "edited": False,
        "deleted": False,
    }
    result = await db["messages"].insert_one(msg)
    msg["_id"] = result.inserted_id
    return serialize_message(msg, "group", {
        "user_id": current_user.user_id,
        "full_name": current_user.full_name,
        "department": current_user.department,
        "role": current_user.role,
    })


@router.post("/groups/{department}/read")
async def mark_group_read(
    department: str,
    db=Depends(get_database),
    current_user: UserInDB = Depends(get_current_user),
):
    """Mark group messages as read for the current user."""
    await ensure_group_access(department, db, current_user)
    conv_id = make_group_conversation_id(department)
    await db["messages"].update_many(
        {
            "conversation_type": "group",
            "conversation_id": conv_id,
            "sender_id": {"$ne": current_user.user_id},
            "read_by": {"$ne": current_user.user_id},
            "deleted": {"$ne": True},
        },
        {"$addToSet": {"read_by": current_user.user_id}},
    )
    return {"status": "ok"}


# ── Message edit/delete ──

@router.patch("/messages/{message_id}")
async def edit_message(
    message_id: str,
    body: UpdateMessageRequest,
    db=Depends(get_database),
    current_user: UserInDB = Depends(get_current_user),
):
    """Edit a message sent by the current user."""
    content = body.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    message = await get_owned_message(db, message_id, current_user)
    now = datetime.utcnow()
    await db["messages"].update_one(
        {"_id": message["_id"]},
        {"$set": {"content": content, "edited": True, "edited_at": now}},
    )
    message.update({"content": content, "edited": True, "edited_at": now})

    sender = None
    if message.get("conversation_type") == "group":
        sender = await db["users"].find_one({"user_id": current_user.user_id})
    return serialize_message(message, sender=sender)


@router.delete("/messages/{message_id}")
async def delete_message(
    message_id: str,
    db=Depends(get_database),
    current_user: UserInDB = Depends(get_current_user),
):
    """Delete a message sent by the current user."""
    message = await get_owned_message(db, message_id, current_user)
    now = datetime.utcnow()
    await db["messages"].update_one(
        {"_id": message["_id"]},
        {"$set": {"deleted": True, "deleted_at": now, "content": ""}},
    )
    return {"status": "ok", "id": message_id, "deleted": True, "deleted_at": serialize_dt(now)}
