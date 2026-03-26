from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
import httpx
from app.core.database import get_database
from app.api.dependencies import get_current_user, get_current_admin
from app.models.user import UserInDB
from app.core.config import settings

router = APIRouter(prefix="/api/vpn", tags=["VPN"])

# In-memory active VPN sessions
active_vpns: dict = {}

ALL_VPNS = [
    {"id": "vpn_eng", "name": "Engineering VPN", "description": "Engineering department network access"},
    {"id": "vpn_hr", "name": "HR VPN", "description": "HR department confidential network"},
    {"id": "vpn_fin", "name": "Finance VPN", "description": "Finance department secure network"},
    {"id": "vpn_sec", "name": "Security VPN", "description": "Security operations network"},
    {"id": "vpn_admin", "name": "Admin VPN", "description": "Administrative systems access"},
]

@router.get("/available")
async def get_available_vpns(db=Depends(get_database), current_user: UserInDB = Depends(get_current_user)):
    state = await db["access_states"].find_one({"_id": current_user.id})
    user_vpns = state.get("vpn_access", []) if state else []
    return [
        {**vpn, "accessible": vpn["id"] in user_vpns}
        for vpn in ALL_VPNS
    ]

@router.get("/access-state/{user_id}")
async def get_vpn_state(user_id: str, current_user: UserInDB = Depends(get_current_user)):
    return {
        "is_connected": user_id in active_vpns,
        "active_vpn": active_vpns.get(user_id)
    }

@router.post("/provision/{vpn_id}")
async def provision_vpn(vpn_id: str, db=Depends(get_database), current_user: UserInDB = Depends(get_current_user)):
    state = await db["access_states"].find_one({"_id": current_user.id})
    if not state or vpn_id not in state.get("vpn_access", []):
        raise HTTPException(status_code=403, detail="Not authorized for this VPN")
    async with httpx.AsyncClient() as client:
        try:
            res = await client.post(f"{settings.VPN_SERVER_URL}/users/{current_user.id}", timeout=10.0)
            res.raise_for_status()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"VPN API error: {e}")
    active_vpns[current_user.id] = vpn_id
    return {"status": "success", "message": f"VPN profile provisioned for {vpn_id}"}

@router.get("/download-profile")
async def download_vpn_profile(current_user: UserInDB = Depends(get_current_user)):
    async with httpx.AsyncClient() as client:
        try:
            res = await client.get(f"{settings.VPN_SERVER_URL}/users/{current_user.id}/download", timeout=10.0)
            if res.status_code != 200:
                raise HTTPException(status_code=404, detail="VPN profile not found. Provision first.")
            return Response(content=res.content, media_type="application/x-openvpn-profile",
                            headers={"Content-Disposition": f"attachment; filename={current_user.id}.ovpn"})
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Download error: {e}")

@router.post("/disconnect")
async def disconnect_vpn(current_user: UserInDB = Depends(get_current_user)):
    active_vpns.pop(current_user.id, None)
    return {"status": "success", "message": "Disconnected"}

@router.post("/revoke/{user_id}")
async def revoke_vpn(user_id: str, db=Depends(get_database), admin=Depends(get_current_admin)):
    async with httpx.AsyncClient() as client:
        try:
            res = await client.post(f"{settings.VPN_SERVER_URL}/users/{user_id}/revoke", timeout=10.0)
            res.raise_for_status()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"VPN revoke error: {e}")
    active_vpns.pop(user_id, None)
    return {"status": "success", "message": f"VPN revoked for {user_id}"}
