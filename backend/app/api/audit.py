from fastapi import APIRouter, Depends
from app.core.database import get_database
from app.api.dependencies import get_current_user, get_current_admin
from app.models.user import UserInDB

router = APIRouter(prefix="/api/audit", tags=["Audit"])

@router.get("/logs")
async def get_audit_logs(db=Depends(get_database), admin=Depends(get_current_admin)):
    cursor = db["audit_logs"].find().sort("timestamp", -1).limit(100)
    logs = await cursor.to_list(length=100)
    for log in logs:
        log.pop("_id", None)
    return logs

@router.delete("/logs/hr")
async def delete_hr_audit_logs(db=Depends(get_database), admin=Depends(get_current_admin)):
    hr_users = await db["users"].find({"department": "HR"}, {"user_id": 1}).to_list(length=None)
    hr_user_ids = [u["user_id"] for u in hr_users]
    if not hr_user_ids:
        return {"deleted": 0}
    result = await db["audit_logs"].delete_many({"user_id": {"$in": hr_user_ids}})
    return {"deleted": result.deleted_count}

@router.get("/logs/user/{user_id}")
async def get_user_audit_logs(user_id: str, db=Depends(get_database), current_user: UserInDB = Depends(get_current_user)):
    if current_user.user_id != user_id and current_user.role not in ["Security Admin", "admin"]:
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Not authorized")
    cursor = db["audit_logs"].find({"$or": [{"user_id": user_id}, {"target_user": user_id}]}).sort("timestamp", -1).limit(50)
    logs = await cursor.to_list(length=50)
    for log in logs:
        log.pop("_id", None)
    return logs
