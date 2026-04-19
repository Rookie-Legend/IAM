from fastapi import APIRouter, Depends
from datetime import datetime
from app.core.database import get_database
from app.api.dependencies import get_current_admin
from app.services.user_status import apply_user_status
from app.services.vpn_catalog import resolve_vpn_request
from app.services.gitlab_sync import backfill_gitlab_users, block_gitlab_user, unblock_gitlab_user

router = APIRouter(prefix="/api/admin", tags=["Admin"])

@router.get("/dashboard")
async def admin_dashboard(db=Depends(get_database), admin=Depends(get_current_admin)):
    total_users = await db["users"].count_documents({})
    disabled_users = await db["users"].count_documents({"disabled": True})
    active_users = await db["vpn_sessions"].count_documents({
        "is_active": True,
        "connected_at": {"$ne": None}
    })
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
    return [await apply_user_status(db, u) for u in users]

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
    gitlab_sync = await block_gitlab_user(user)
    return {
        "status": "success",
        "message": f"User {user_id} has been disabled",
        "gitlab_sync": gitlab_sync.as_dict(),
    }

@router.post("/users/{user_id}/reinstate")
async def reinstate_user(user_id: str, db=Depends(get_database), admin=Depends(get_current_admin)):
    user = await db["users"].find_one({"user_id": user_id})
    if not user:
        return {"status": "error", "message": f"User {user_id} not found"}
    if not user.get("disabled"):
        return {"status": "error", "message": f"User {user_id} is already active"}
    await db["users"].update_one({"user_id": user_id}, {"$set": {"status": "inactive", "disabled": False}})
    await db["audit_logs"].insert_one({
        "user_id": admin.user_id,
        "action": "reinstate_user",
        "target_user": user_id,
        "target_name": user.get("full_name", ""),
        "details": f"Admin {admin.user_id} ({admin.role}) reinstated user {user_id} ({user.get('full_name', '')}) - previously disabled",
        "timestamp": datetime.utcnow()
    })
    gitlab_sync = await unblock_gitlab_user(user)
    return {
        "status": "success",
        "message": f"User {user_id} has been reinstated",
        "gitlab_sync": gitlab_sync.as_dict(),
    }

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
    gitlab_sync = await block_gitlab_user(user)
    return {
        "status": "success",
        "message": f"User {user_id} has been offboarded and all access revoked",
        "gitlab_sync": gitlab_sync.as_dict(),
    }

@router.post("/gitlab-sync")
async def sync_gitlab_users(db=Depends(get_database), admin=Depends(get_current_admin)):
    users = await db["users"].find({}).to_list(length=1000)
    summary = await backfill_gitlab_users(users)
    await db["audit_logs"].insert_one({
        "user_id": admin.user_id,
        "action": "gitlab_sync",
        "target_resource": "gitlab",
        "details": f"Admin {admin.user_id} ran GitLab backfill sync: {summary}",
        "timestamp": datetime.utcnow()
    })
    return {"status": "success", "summary": summary}

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

    user_id = access_req.get("user_id")
    resource_type = access_req.get("resource_type")
    if resource_type and "vpn" in resource_type.lower():
        resolved_vpn_id, pools = await resolve_vpn_request(db, resource_type)
        if not resolved_vpn_id:
            available_vpns = ", ".join(pool.get("pool_id", "") for pool in pools) or "none"
            return {
                "status": "error",
                "message": f"Requested VPN is not available. Available VPNs: {available_vpns}"
            }
        resource_type = resolved_vpn_id

    await db["access_requests"].update_one(
        {"_id": ObjectId(request_id)},
        {"$set": {"status": "approved", "resource_type": resource_type, "decided_at": datetime.utcnow()}}
    )

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
        "target_resource": resource_type or request_id,
        "target_user": access_req.get("user_id", "") if access_req else "",
        "details": f"Admin {admin.user_id} ({admin.role}) approved {resource_type or 'access'} request for user {access_req.get('user_id', '')}",
        "timestamp": datetime.utcnow()
    })
    return {"status": "success", "message": "Access request approved"}

@router.post("/access-requests/{request_id}/deny")
async def deny_access_request(request_id: str, db=Depends(get_database), admin=Depends(get_current_admin)):
    from bson import ObjectId
    access_req = await db["access_requests"].find_one({"_id": ObjectId(request_id)})
    if not access_req:
        return {"status": "error", "message": "Access request not found"}
    
    await db["access_requests"].update_one({"_id": ObjectId(request_id)}, {"$set": {"status": "denied", "decided_at": datetime.utcnow()}})
    
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

# ── Admin Escalation Notification endpoints ──

@router.get("/escalation-notifications")
async def get_escalation_notifications(db=Depends(get_database), admin=Depends(get_current_admin)):
    """Return pending escalation requests that the admin hasn't dismissed from the bell."""
    cursor = db["access_requests"].find({
        "status": "pending",
        "admin_notif_dismissed": {"$ne": True}
    }).sort("timestamp", -1)
    requests = await cursor.to_list(length=100)
    result = []
    for r in requests:
        ts = r.get("timestamp")
        result.append({
            "id": str(r["_id"]),
            "user_id": r.get("user_id", "Unknown"),
            "resource_type": r.get("resource_type", "Unknown"),
            "timestamp": (ts.strftime('%Y-%m-%dT%H:%M:%S.') + f'{ts.microsecond:06d}'[:3] + 'Z') if ts else None,
        })
    return result

@router.post("/escalation-notifications/{request_id}/dismiss")
async def dismiss_escalation_notification(request_id: str, db=Depends(get_database), admin=Depends(get_current_admin)):
    """Mark a pending escalation notification as dismissed from the bell (does NOT approve/deny the request)."""
    from bson import ObjectId
    from fastapi import HTTPException
    result = await db["access_requests"].update_one(
        {"_id": ObjectId(request_id)},
        {"$set": {"admin_notif_dismissed": True}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"status": "dismissed"}
