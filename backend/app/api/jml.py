from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from datetime import datetime, timedelta
import random
import string
from app.core.database import get_database
from app.core.security import get_password_hash
from app.api.dependencies import get_current_admin
from app.api.vpn import revoke_vpn
from app.services.email_service import send_email
from app.core.config import settings
from app.services.gitlab_sync import block_gitlab_user, ensure_gitlab_user, unblock_gitlab_user

router = APIRouter(prefix="/api/jml", tags=["JML"])

class JMLEventRequest(BaseModel):
    user_id: str
    event_type: str
    department: str = None
    role: str = None
    email: str = None
    full_name: str = None

class InviteRequest(BaseModel):
    email: str
    role: str
    department: str = "Engineering"

@router.post("/invite")
async def create_invite(request: InviteRequest, db=Depends(get_database), admin=Depends(get_current_admin)):
    existing_user = await db["users"].find_one({"email": request.email})
    if existing_user:
        raise HTTPException(status_code=400, detail="User with this email already exists")

    existing_invite = await db["invites"].find_one({"email": request.email, "status": "pending"})
    if existing_invite:
        await db["invites"].update_one({"email": request.email}, {"$set": {"status": "expired"}})

    token = ''.join(random.choices(string.ascii_letters + string.digits, k=32))
    invite = {
        "email": request.email,
        "role": request.role,
        "department": request.department,
        "token": token,
        "status": "pending",
        "created_at": datetime.utcnow(),
        "expires_at": datetime.utcnow() + timedelta(days=3),
        "created_by": admin.user_id
    }
    await db["invites"].insert_one(invite)

    login_link = f"{settings.FRONTEND_URL}/login?invite=true&token={token}"
    await send_email(request.email, "Welcome to CorpOD - Complete Your Registration", "invite_email.html", {"ROLE": request.role, "DEPARTMENT": request.department, "LOGIN_LINK": login_link})

    await db["audit_logs"].insert_one({
        "user_id": admin.user_id,
        "action": "invite",
        "target_user": request.email,
        "details": f"Admin {admin.user_id} ({admin.role}) sent invite to {request.email} for role {request.role}",
        "timestamp": datetime.utcnow()
    })

    return {"status": "success", "message": f"Invitation sent to {request.email}"}

@router.post("/event")
async def process_jml_event(request: JMLEventRequest, db=Depends(get_database), admin=Depends(get_current_admin)):
    now = datetime.utcnow()

    if request.event_type == "joiner":
        existing = await db["users"].find_one({"user_id": request.user_id})
        if existing:
            raise HTTPException(status_code=400, detail="User already exists")
        new_user = {
            "user_id": request.user_id,
            "username": request.user_id,
            "email": request.email or f"{request.user_id}@company.com",
            "full_name": request.full_name or request.user_id,
            "department": request.department or "engineering",
            "role": request.role or "software_engineer",
            "status": "inactive",
            "disabled": False,
            "hashed_password": get_password_hash("TempPass@123")
        }
        await db["users"].insert_one(new_user)
        gitlab_sync = await ensure_gitlab_user(new_user, "TempPass@123")
        await db["access_states"].insert_one({
            "user_id": request.user_id,
            "vpn_access": [],
            "connected": False,
            "connected_vpn": None,
            "connected_ip": None,
            "connected_at": None,
            "last_disconnected_at": None
        })
        await db["audit_logs"].insert_one({
            "user_id": admin.user_id,
            "action": "joiner",
            "target_user": request.user_id,
            "target_name": new_user["full_name"],
            "details": f"Admin {admin.user_id} ({admin.role}) onboarded new employee {request.user_id} ({new_user['full_name']}) in {new_user['department']} as {new_user['role']}",
            "timestamp": now
        })
        return {
            "status": "success",
            "message": f"User {request.user_id} onboarded. Temp password: TempPass@123",
            "gitlab_sync": gitlab_sync.as_dict(),
        }

    elif request.event_type == "leaver":
        user = await db["users"].find_one({"user_id": request.user_id})
        await db["users"].update_one({"user_id": request.user_id}, {"$set": {"status": "inactive", "disabled": True}})
        await db["access_states"].update_one({"user_id": request.user_id}, {"$set": {
            "vpn_access": [],
            "connected": False,
            "connected_vpn": None,
            "connected_ip": None,
            "connected_at": None,
            "last_disconnected_at": datetime.utcnow()
        }})
        await db["audit_logs"].insert_one({
            "user_id": admin.user_id,
            "action": "leaver",
            "target_user": request.user_id,
            "target_name": user.get("full_name", "") if user else "",
            "details": f"Admin {admin.user_id} ({admin.role}) offboarded user {request.user_id} ({user.get('full_name', '') if user else ''}) from {user.get('department', '') if user else ''}. All access revoked.",
            "timestamp": now
        })
        try:
            await revoke_vpn(user_id=request.user_id, db=db, admin=admin)
        except Exception:
            pass
        gitlab_sync = await block_gitlab_user(user or {"user_id": request.user_id})
        return {
            "status": "success",
            "message": f"User {request.user_id} offboarded and disabled",
            "gitlab_sync": gitlab_sync.as_dict(),
        }

    elif request.event_type == "mover":
        user = await db["users"].find_one({"user_id": request.user_id})
        old_dept = user.get("department", "") if user else ""
        old_role = user.get("role", "") if user else ""
        await db["users"].update_one(
            {"user_id": request.user_id},
            {"$set": {"department": request.department, "role": request.role or "software_engineer"}}
        )
        await db["access_states"].update_one(
            {"user_id": request.user_id},
            {"$set": {
                "vpn_access": [],
                "connected": False,
                "connected_vpn": None,
                "connected_ip": None,
                "connected_at": None,
                "last_disconnected_at": datetime.utcnow()
            }}
        )
        await db["audit_logs"].insert_one({
            "user_id": admin.user_id,
            "action": "mover",
            "target_user": request.user_id,
            "target_name": user.get("full_name", "") if user else "",
            "details": f"Admin {admin.user_id} ({admin.role}) transferred user {request.user_id} ({user.get('full_name', '') if user else ''}) from {old_dept}/{old_role} to {request.department}/{request.role or 'software_engineer'}. VPN access revoked.",
            "timestamp": now
        })
        try:
            await revoke_vpn(user_id=request.user_id, db=db, admin=admin)
        except Exception:
            pass
        return {"status": "success", "message": f"User {request.user_id} moved to {request.department}. VPN access revoked, user must request access again."}

    elif request.event_type == "reinstate":
        user = await db["users"].find_one({"user_id": request.user_id})
        await db["users"].update_one({"user_id": request.user_id}, {"$set": {"status": "inactive", "disabled": False}})
        await db["audit_logs"].insert_one({
            "user_id": admin.user_id,
            "action": "reinstate",
            "target_user": request.user_id,
            "target_name": user.get("full_name", "") if user else "",
            "details": f"Admin {admin.user_id} ({admin.role}) reinstated user {request.user_id} ({user.get('full_name', '') if user else ''}) - previously disabled. Account is now active.",
            "timestamp": now
        })
        gitlab_sync = await unblock_gitlab_user(user or {"user_id": request.user_id})
        return {
            "status": "success",
            "message": f"User {request.user_id} reinstated",
            "gitlab_sync": gitlab_sync.as_dict(),
        }

    raise HTTPException(status_code=400, detail=f"Unknown event type: {request.event_type}")
