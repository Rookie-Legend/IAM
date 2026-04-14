from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel
from datetime import datetime
import httpx
from app.core.database import get_database
from app.api.dependencies import get_current_user, get_current_admin
from app.models.user import UserInDB
from app.core.config import settings

router = APIRouter(prefix="/api/vpn", tags=["VPN"])

class AllocateRequest(BaseModel):
    vpn_id: str
    department: str = "Engineering"

@router.get("/available")
async def get_available_vpns(db=Depends(get_database), current_user: UserInDB = Depends(get_current_user)):
    state = await db["access_states"].find_one({"user_id": current_user.user_id})
    user_vpns = state.get("vpn_access", []) if state else []
    provisioned_vpn = state.get("provisioned_vpn") if state else None
    has_provisioned = bool(state.get("has_provisioned")) if state else False
    
    active_session = await db["vpn_sessions"].find_one({
        "user_id": current_user.user_id,
        "is_active": True,
        "connected_at": {"$ne": None}
    })
    current_vpn = active_session["vpn_id"] if active_session else None
    
    pools_cursor = db["vpn_ip_pools"].find({"is_active": True})
    pools = await pools_cursor.to_list(length=100)
    
    return [
        {
            "id": pool["pool_id"],
            "name": pool["name"],
            "description": f"{pool['department']} department network",
            "department": pool["department"],
            "accessible": pool["pool_id"] in user_vpns,
            "is_current": pool["pool_id"] == current_vpn,
            "has_provisioned": has_provisioned and pool["pool_id"] == provisioned_vpn,
            "has_any_provisioned": has_provisioned,
            "has_active": current_vpn is not None and pool["pool_id"] != current_vpn
        }
        for pool in pools
    ]

@router.get("/my-status")
async def get_my_status(db=Depends(get_database), current_user: UserInDB = Depends(get_current_user)):
    state = await db["access_states"].find_one({"user_id": current_user.user_id})
    active_session = await db["vpn_sessions"].find_one({
        "user_id": current_user.user_id,
        "is_active": True,
        "connected_at": {"$ne": None}
    })

    if not state:
        return {
            "is_connected": False,
            "has_provisioned": False,
            "provisioned_vpn": None,
            "connected_vpn": active_session.get("vpn_id") if active_session else None,
            "connected_ip": (active_session.get("vpn_ip") or active_session.get("assigned_ip")) if active_session else None,
            "connected_at": active_session.get("connected_at") if active_session else None
        }

    derived_connected = bool(active_session)
    derived_vpn = (active_session.get("vpn_id") if active_session else None) or state.get("connected_vpn")
    derived_ip = ((active_session.get("vpn_ip") or active_session.get("assigned_ip")) if active_session else None) or state.get("connected_ip")
    derived_connected_at = (active_session.get("connected_at") if active_session else None) or state.get("connected_at")
    derived_provisioned = bool(state.get("has_provisioned", False))
    derived_provisioned_vpn = state.get("provisioned_vpn")

    return {
        "is_connected": derived_connected,
        "has_provisioned": derived_provisioned,
        "provisioned_vpn": derived_provisioned_vpn,
        "connected_vpn": derived_vpn,
        "connected_ip": derived_ip,
        "connected_at": derived_connected_at
    }

@router.post("/provision/{vpn_id}")
async def provision_vpn(vpn_id: str, db=Depends(get_database), current_user: UserInDB = Depends(get_current_user)):
    state = await db["access_states"].find_one({"user_id": current_user.user_id})
    if not state or vpn_id not in state.get("vpn_access", []):
        raise HTTPException(status_code=403, detail="Not authorized for this VPN")

    active_session = await db["vpn_sessions"].find_one({
        "user_id": current_user.user_id,
        "is_active": True,
        "connected_at": {"$ne": None}
    })
    
    if active_session:
        if active_session["vpn_id"] == vpn_id:
            return {"status": "already_active", "message": "VPN already active", "ip": active_session["assigned_ip"]}
        raise HTTPException(
            status_code=409,
            detail=f"You have an active VPN ({active_session['vpn_id']}). Use Switch to change VPNs or revoke first."
        )

    if state.get("has_provisioned") and state.get("provisioned_vpn"):
        if state["provisioned_vpn"] == vpn_id:
            return {"status": "already_provisioned", "message": "VPN profile already provisioned"}
        raise HTTPException(
            status_code=409,
            detail=f"You already have a provisioned VPN ({state['provisioned_vpn']}). Use Switch to change it or revoke first."
        )

    pool = await db["vpn_ip_pools"].find_one({"pool_id": vpn_id, "is_active": True})
    if not pool:
        raise HTTPException(status_code=404, detail="VPN pool not found")
    department = pool["department"]

    async with httpx.AsyncClient() as client:
        try:
            res = await client.post(
                f"{settings.VPN_SERVER_URL}/users/{current_user.user_id}",
                json={"vpn_id": vpn_id, "department": department},
                timeout=10.0
            )
            res.raise_for_status()
            result = res.json()
        except httpx.HTTPStatusError as e:
            raise HTTPException(status_code=e.response.status_code, detail=f"VPN API error: {e.response.text}")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"VPN API error: {str(e)}")

    return {"status": "success", "message": f"VPN profile provisioned for {vpn_id}", "ip": result.get("ip")}

@router.post("/switch/{new_vpn_id}")
async def switch_vpn(new_vpn_id: str, db=Depends(get_database), current_user: UserInDB = Depends(get_current_user)):
    state = await db["access_states"].find_one({"user_id": current_user.user_id})
    if not state or new_vpn_id not in state.get("vpn_access", []):
        raise HTTPException(status_code=403, detail="Not authorized for this VPN")

    active_session = await db["vpn_sessions"].find_one({
        "user_id": current_user.user_id,
        "is_active": True,
        "connected_at": {"$ne": None}
    })
    provisioned_session = await db["vpn_sessions"].find_one({"user_id": current_user.user_id})

    current_vpn_id = (
        active_session["vpn_id"] if active_session else
        (state.get("provisioned_vpn") or (provisioned_session.get("vpn_id") if provisioned_session else None))
    )
    current_ip = (
        active_session.get("assigned_ip") if active_session else
        (provisioned_session.get("assigned_ip") if provisioned_session else None)
    )

    if not current_vpn_id:
        raise HTTPException(status_code=400, detail="No provisioned VPN to switch from. Use Provision instead.")

    if current_vpn_id == new_vpn_id:
        if active_session:
            return {"status": "already_active", "message": "Already on this VPN", "ip": current_ip}
        return {"status": "already_provisioned", "message": "VPN profile already provisioned", "ip": current_ip}

    async with httpx.AsyncClient() as client:
        try:
            revoke_res = await client.post(
                f"{settings.VPN_SERVER_URL}/users/{current_user.user_id}/revoke",
                timeout=10.0
            )
            revoke_res.raise_for_status()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to revoke current VPN: {str(e)}")

        pool = await db["vpn_ip_pools"].find_one({"pool_id": new_vpn_id, "is_active": True})
        if not pool:
            raise HTTPException(status_code=404, detail="VPN pool not found")
        department = pool["department"]

        try:
            provision_res = await client.post(
                f"{settings.VPN_SERVER_URL}/users/{current_user.user_id}",
                json={"vpn_id": new_vpn_id, "department": department},
                timeout=10.0
            )
            provision_res.raise_for_status()
            result = provision_res.json()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to provision new VPN: {str(e)}")

    return {
        "status": "success",
        "message": f"Switched from {current_vpn_id} ({current_ip}) to {new_vpn_id} ({result.get('ip')})",
        "old_vpn": current_vpn_id,
        "new_vpn": new_vpn_id,
        "ip": result.get("ip")
    }

@router.get("/download-profile")
async def download_vpn_profile(db=Depends(get_database), current_user: UserInDB = Depends(get_current_user)):
    state = await db["access_states"].find_one({"user_id": current_user.user_id})
    
    if not state or not state.get("has_provisioned"):
        raise HTTPException(status_code=403, detail="No VPN provisioned. Please provision a VPN first.")

    async with httpx.AsyncClient() as client:
        try:
            res = await client.get(f"{settings.VPN_SERVER_URL}/users/{current_user.user_id}/download", timeout=10.0)
            if res.status_code != 200:
                raise HTTPException(status_code=404, detail="VPN profile not found. Please provision again.")
            return Response(content=res.content, media_type="application/x-openvpn-profile",
                            headers={"Content-Disposition": f"attachment; filename={current_user.user_id}.ovpn"})
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Download error: {str(e)}")

@router.post("/disconnect")
async def disconnect_vpn(db=Depends(get_database), current_user: UserInDB = Depends(get_current_user)):
    state = await db["access_states"].find_one({"user_id": current_user.user_id})
    active_session = await db["vpn_sessions"].find_one({
        "user_id": current_user.user_id,
        "is_active": True
    })
    
    if not active_session and not (state and state.get("has_provisioned")):
        return {"status": "success", "message": "No active session or provisioned VPN to revoke"}

    async with httpx.AsyncClient() as client:
        try:
            res = await client.post(
                f"{settings.VPN_SERVER_URL}/users/{current_user.user_id}/revoke",
                timeout=10.0
            )
            res.raise_for_status()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Disconnect error: {str(e)}")

    return {"status": "success", "message": "Disconnected and access revoked"}

@router.post("/revoke/{user_id}")
async def revoke_vpn(user_id: str, db=Depends(get_database), admin=Depends(get_current_admin)):
    async with httpx.AsyncClient() as client:
        try:
            res = await client.post(f"{settings.VPN_SERVER_URL}/users/{user_id}/revoke", timeout=10.0)
            res.raise_for_status()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"VPN revoke error: {str(e)}")

    return {"status": "success", "message": f"VPN revoked for {user_id}"}

@router.get("/audit-logs")
async def get_audit_logs(
    limit: int = Query(50, le=500),
    event_type: str = Query(""),
    user_id: str = Query(""),
    current_user: UserInDB = Depends(get_current_user)
):
    async with httpx.AsyncClient() as client:
        try:
            params = {"limit": limit}
            if event_type:
                params["event_type"] = event_type
            if user_id:
                params["user_id"] = user_id
            res = await client.get(f"{settings.VPN_SERVER_URL}/events", params=params, timeout=10.0)
            res.raise_for_status()
            events = res.json()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to fetch VPN events: {str(e)}")

    return {"logs": events, "count": len(events)}

@router.get("/admin/sessions")
async def get_all_sessions(
    db=Depends(get_database),
    admin=Depends(get_current_admin)
):
    cursor = db["vpn_sessions"].find({"is_active": True}).sort("connected_at", -1)
    sessions = await cursor.to_list(length=500)
    
    for session in sessions:
        session["_id"] = str(session["_id"])
        if session.get("connected_at"):
            session["connected_at"] = session["connected_at"].isoformat()
        if session.get("last_activity"):
            session["last_activity"] = session["last_activity"].isoformat()

    return {"sessions": sessions, "count": len(sessions)}

@router.get("/admin/pools")
async def get_ip_pools(db=Depends(get_database), admin=Depends(get_current_admin)):
    cursor = db["vpn_ip_pools"].find({})
    pools = await cursor.to_list(length=10)
    
    for pool in pools:
        pool["_id"] = str(pool["_id"])

    return {"pools": pools}
