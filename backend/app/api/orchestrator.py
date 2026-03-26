from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from app.core.database import get_database
from app.api.dependencies import get_current_user
from app.models.user import UserInDB
from app.models.access_state import AccessStateInDB

router = APIRouter(prefix="/api/orchestrator", tags=["Orchestrator"])

class AccessRequestModel(BaseModel):
    user_id: str
    resource_id: str

@router.get("/access/{user_id}")
async def get_access_state(user_id: str, db=Depends(get_database), current_user: UserInDB = Depends(get_current_user)):
    if current_user.id != user_id and current_user.role not in ["Security Admin", "admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    state = await db["access_states"].find_one({"_id": user_id})
    if not state:
        raise HTTPException(status_code=404, detail="Access state not found")
    return state

@router.post("/request-access")
async def request_access(request: AccessRequestModel, db=Depends(get_database), current_user: UserInDB = Depends(get_current_user)):
    user = await db["users"].find_one({"_id": request.user_id})
    if request.resource_id == "critical_server":
        return {"status": "MFA_CHALLENGE", "message": "Step-up authentication required"}
    if user and "admin" in request.resource_id and user.get("role") not in ["Security Admin", "admin"]:
        return {"status": "DENY", "message": "Access denied by policy"}
    return {"status": "GRANT", "message": "Access granted"}
