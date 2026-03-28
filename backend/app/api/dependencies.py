from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from app.core.config import settings
from app.core.database import get_database
from app.models.user import UserInDB

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

async def get_current_user(token: str = Depends(oauth2_scheme), db=Depends(get_database)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user_data = await db["users"].find_one({"user_id": user_id})
    if user_data is None:
        user_data = await db["users"].find_one({"username": user_id})
    if user_data is None:
        raise credentials_exception

    if user_data.get("disabled", False):
        raise HTTPException(status_code=400, detail="Your account has been disabled.")

    return UserInDB(**user_data)

async def get_current_admin(current_user: UserInDB = Depends(get_current_user)):
    admin_roles = ["Security Admin", "System Administrator", "HR Manager", "admin"]
    if current_user.role not in admin_roles:
        raise HTTPException(status_code=403, detail="Admin privileges required.")
    return current_user
