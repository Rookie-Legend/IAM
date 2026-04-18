from fastapi import APIRouter, Depends, HTTPException
from bson import ObjectId
from app.core.database import get_database
from app.core.security import get_password_hash
from app.api.dependencies import get_current_user, get_current_admin
from app.models.user import UserInDB, UserCreate
from app.services.user_status import apply_user_status

router = APIRouter(prefix="/api/users", tags=["Users"])

@router.get("/me")
async def get_me(current_user: UserInDB = Depends(get_current_user)):
    return current_user

# ── Notification endpoints must come BEFORE /{user_id} to avoid wildcard capture ──

@router.get("/my-notifications")
async def get_my_notifications(db=Depends(get_database), current_user: UserInDB = Depends(get_current_user)):
    """Return approved/denied access requests for current user that haven't been dismissed."""
    cursor = db["access_requests"].find({
        "user_id": current_user.user_id,
        "status": {"$in": ["approved", "denied"]},
        "notif_dismissed": {"$ne": True}
    }).sort("timestamp", -1)
    requests = await cursor.to_list(length=50)
    result = []
    for r in requests:
        # Prefer decided_at (when admin actioned), fall back to original request timestamp
        ts = r.get("decided_at") or r.get("timestamp")
        result.append({
            "id": str(r["_id"]),
            "resource_type": r.get("resource_type", "Unknown"),
            "status": r.get("status"),
            "timestamp": (ts.strftime('%Y-%m-%dT%H:%M:%S.') + f'{ts.microsecond:06d}'[:3] + 'Z') if ts else None,
        })
    return result

@router.post("/my-notifications/{request_id}/dismiss")
async def dismiss_notification(request_id: str, db=Depends(get_database), current_user: UserInDB = Depends(get_current_user)):
    """Mark a notification as dismissed so it no longer appears in the bell."""
    result = await db["access_requests"].update_one(
        {"_id": ObjectId(request_id), "user_id": current_user.user_id},
        {"$set": {"notif_dismissed": True}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"status": "dismissed"}

# ── Generic user lookup — keep AFTER all literal paths ──

@router.get("/{user_id}")
async def get_user(user_id: str, db=Depends(get_database), current_user: UserInDB = Depends(get_current_user)):
    if current_user.user_id != user_id and current_user.role not in ["Security Admin", "System Administrator", "admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    user = await db["users"].find_one({"user_id": user_id})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.pop("hashed_password", None)
    user.pop("_id", None)
    return await apply_user_status(db, user)

@router.get("/")
async def list_users(db=Depends(get_database), admin=Depends(get_current_admin)):
    cursor = db["users"].find({}, {"hashed_password": 0, "_id": 0})
    users = await cursor.to_list(length=100)
    return [await apply_user_status(db, u) for u in users]

@router.get("/department/members")
async def get_department_members(db=Depends(get_database), current_user: UserInDB = Depends(get_current_user)):
    cursor = db["users"].find({"department": current_user.department}, {"hashed_password": 0, "_id": 0})
    users = await cursor.to_list(length=100)
    return [await apply_user_status(db, u) for u in users]
