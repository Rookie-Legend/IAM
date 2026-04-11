from fastapi import APIRouter, Depends
from datetime import datetime
from app.core.database import get_database
from app.api.dependencies import get_current_admin

router = APIRouter(prefix="/api/admin", tags=["Admin"])

@router.get("/dashboard")
async def admin_dashboard(db=Depends(get_database), admin=Depends(get_current_admin)):
    total_users = await db["users"].count_documents({})
    active_users = await db["users"].count_documents({"status": "active", "disabled": False})
    disabled_users = await db["users"].count_documents({"disabled": True})
    total_policies = await db["policies"].count_documents({})
    pending_requests = await db["access_requests"].count_documents({"status": "pending"})
    return {
        "total_users": total_users,
        "active_users": active_users,
        "disabled_users": disabled_users,
        "total_policies": total_policies,
        "pending_access_requests": pending_requests
    }

@router.get("/users")
async def list_all_users(db=Depends(get_database), admin=Depends(get_current_admin)):
    cursor = db["users"].find({}, {"hashed_password": 0}).sort("department", 1)
    users = await cursor.to_list(length=500)
    for u in users:
        u["_id"] = str(u["_id"])
        u["user_id"] = str(u.get("user_id", u["_id"]))
        u["id"] = str(u.get("user_id", u["_id"]))
    return users

@router.post("/users/{user_id}/disable")
async def disable_user(user_id: str, db=Depends(get_database), admin=Depends(get_current_admin)):
    user = await db["users"].find_one({"user_id": user_id})
    if not user:
        return {"status": "error", "message": f"User {user_id} not found"}
    if user.get("disabled"):
        return {"status": "error", "message": f"User {user_id} is already disabled"}
    await db["users"].update_one({"user_id": user_id}, {"$set": {"status": "inactive", "disabled": True}})
    await db["access_states"].update_one({"user_id": user_id}, {"$set": {
        "vpn_access": [],
        "connected": False,
        "connected_vpn": None,
        "connected_ip": None,
        "connected_at": None,
        "last_disconnected_at": datetime.utcnow()
    }})
    await db["audit_logs"].insert_one({
        "user_id": admin.user_id,
        "action": "disable_user",
        "target_user": user_id,
        "target_name": user.get("full_name", ""),
        "details": f"Admin {admin.user_id} ({admin.role}) disabled user {user_id} ({user.get('full_name', '')}) from department {user.get('department', '')}",
        "timestamp": datetime.utcnow()
    })
    return {"status": "success", "message": f"User {user_id} has been disabled"}

@router.post("/users/{user_id}/reinstate")
async def reinstate_user(user_id: str, db=Depends(get_database), admin=Depends(get_current_admin)):
    user = await db["users"].find_one({"user_id": user_id})
    if not user:
        return {"status": "error", "message": f"User {user_id} not found"}
    if not user.get("disabled"):
        return {"status": "error", "message": f"User {user_id} is already active"}
    await db["users"].update_one({"user_id": user_id}, {"$set": {"status": "active", "disabled": False}})
    await db["audit_logs"].insert_one({
        "user_id": admin.user_id,
        "action": "reinstate_user",
        "target_user": user_id,
        "target_name": user.get("full_name", ""),
        "details": f"Admin {admin.user_id} ({admin.role}) reinstated user {user_id} ({user.get('full_name', '')}) - previously disabled",
        "timestamp": datetime.utcnow()
    })
    return {"status": "success", "message": f"User {user_id} has been reinstated"}

@router.post("/users/{user_id}/offboard")
async def offboard_user(user_id: str, db=Depends(get_database), admin=Depends(get_current_admin)):
    user = await db["users"].find_one({"user_id": user_id})
    if not user:
        return {"status": "error", "message": f"User {user_id} not found"}
    if user.get("disabled"):
        return {"status": "error", "message": f"User {user_id} is already offboarded/disabled"}
    await db["users"].update_one({"user_id": user_id}, {"$set": {"status": "inactive", "disabled": True}})
    await db["access_states"].update_one({"user_id": user_id}, {"$set": {
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
        "target_user": user_id,
        "target_name": user.get("full_name", ""),
        "details": f"Admin {admin.user_id} ({admin.role}) offboarded user {user_id} ({user.get('full_name', '')}) from department {user.get('department', '')}. All access revoked.",
        "timestamp": datetime.utcnow()
    })
    return {"status": "success", "message": f"User {user_id} has been offboarded and all access revoked"}

@router.get("/access-requests")
async def get_access_requests(db=Depends(get_database), admin=Depends(get_current_admin)):
    cursor = db["access_requests"].find({"status": "pending"}).sort("timestamp", -1)
    requests = await cursor.to_list(length=100)
    for r in requests:
        r["id"] = str(r.pop("_id", ""))
    return requests

@router.post("/access-requests/{request_id}/approve")
async def approve_access_request(request_id: str, db=Depends(get_database), admin=Depends(get_current_admin)):
    from bson import ObjectId
    access_req = await db["access_requests"].find_one({"_id": ObjectId(request_id)})
    if not access_req:
        return {"status": "error", "message": "Access request not found"}
    
    await db["access_requests"].update_one({"_id": ObjectId(request_id)}, {"$set": {"status": "approved"}})
    
    user_id = access_req.get("user_id")
    resource_type = access_req.get("resource_type")
    if user_id and resource_type:
        state = await db["access_states"].find_one({"user_id": user_id})
        field = "vpn_access" if "vpn" in (resource_type or "") else "resources"
        if state:
            existing = state.get(field, [])
            if resource_type not in existing:
                existing.append(resource_type)
                await db["access_states"].update_one(
                    {"user_id": user_id},
                    {"$set": {
                        field: existing,
                        "connected": False,
                        "connected_vpn": None,
                        "connected_ip": None,
                        "connected_at": None,
                        "last_disconnected_at": None
                    }}
                )
        else:
            await db["access_states"].insert_one({
                "user_id": user_id,
                "vpn_access": [resource_type] if field == "vpn_access" else [],
                "resources": [resource_type] if field == "resources" else [],
                "connected": False,
                "connected_vpn": None,
                "connected_ip": None,
                "connected_at": None,
                "last_disconnected_at": None
            })
        
        await db["audit_logs"].update_one(
            {"user_id": user_id, "target_resource": resource_type, "action": "ESCALATE"},
            {"$set": {"action": "ESCALATE_ACCEPTED"}}
        )
    
    await db["audit_logs"].insert_one({
        "user_id": admin.user_id,
        "action": "approve_access",
        "target_resource": access_req.get("resource_type", "unknown") if access_req else request_id,
        "target_user": access_req.get("user_id", "") if access_req else "",
        "details": f"Admin {admin.user_id} ({admin.role}) approved {access_req.get('resource_type', 'access')} request for user {access_req.get('user_id', '')}",
        "timestamp": datetime.utcnow()
    })
    return {"status": "success", "message": "Access request approved"}

@router.post("/access-requests/{request_id}/deny")
async def deny_access_request(request_id: str, db=Depends(get_database), admin=Depends(get_current_admin)):
    from bson import ObjectId
    access_req = await db["access_requests"].find_one({"_id": ObjectId(request_id)})
    if not access_req:
        return {"status": "error", "message": "Access request not found"}
    
    await db["access_requests"].update_one({"_id": ObjectId(request_id)}, {"$set": {"status": "denied"}})
    
    user_id = access_req.get("user_id")
    resource_type = access_req.get("resource_type")
    if user_id and resource_type:
        await db["audit_logs"].update_one(
            {"user_id": user_id, "target_resource": resource_type, "action": "ESCALATE"},
            {"$set": {"action": "ESCALATE_DENIED"}}
        )
    
    await db["audit_logs"].insert_one({
        "user_id": admin.user_id,
        "action": "deny_access",
        "target_resource": access_req.get("resource_type", "unknown") if access_req else request_id,
        "target_user": access_req.get("user_id", "") if access_req else "",
        "details": f"Admin {admin.user_id} ({admin.role}) denied {access_req.get('resource_type', 'access')} request for user {access_req.get('user_id', '')}",
        "timestamp": datetime.utcnow()
    })
    return {"status": "success", "message": "Access request denied"}