from fastapi import APIRouter, Depends, HTTPException
from app.core.database import get_database
from app.core.security import get_password_hash
from app.api.dependencies import get_current_user, get_current_admin
from app.models.user import UserInDB, UserCreate

router = APIRouter(prefix="/api/users", tags=["Users"])

@router.get("/me")
async def get_me(current_user: UserInDB = Depends(get_current_user)):
    return current_user

@router.get("/{user_id}")
async def get_user(user_id: str, db=Depends(get_database), current_user: UserInDB = Depends(get_current_user)):
    if current_user.id != user_id and current_user.role not in ["Security Admin", "System Administrator", "admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    user = await db["users"].find_one({"_id": user_id})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.pop("hashed_password", None)
    return user

@router.get("/")
async def list_users(db=Depends(get_database), admin=Depends(get_current_admin)):
    cursor = db["users"].find({}, {"hashed_password": 0})
    users = await cursor.to_list(length=100)
    return users
