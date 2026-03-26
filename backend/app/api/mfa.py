from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from app.core.database import get_database
from app.api.dependencies import get_current_user
from app.models.user import UserInDB
from app.services.otp_service import otp_service

router = APIRouter(prefix="/api/mfa", tags=["MFA"])

class OTPVerifyRequest(BaseModel):
    otp: str

@router.post("/generate")
async def generate_otp(db=Depends(get_database), current_user: UserInDB = Depends(get_current_user)):
    try:
        await otp_service.generate_otp(current_user.id, current_user.email, db)
        return {"status": "success", "message": "OTP sent to your registered email."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate OTP: {e}")

@router.post("/verify")
async def verify_otp(request: OTPVerifyRequest, db=Depends(get_database), current_user: UserInDB = Depends(get_current_user)):
    verified = await otp_service.verify_otp(current_user.id, request.otp, db)
    if verified:
        await db["audit_logs"].update_many(
            {"user_id": current_user.id, "mfa_status": "pending"},
            {"$set": {"mfa_status": "verified"}}
        )
        return {"status": "success", "message": "OTP verified successfully"}
    await db["audit_logs"].update_many(
        {"user_id": current_user.id, "mfa_status": "pending"},
        {"$set": {"mfa_status": "failed"}}
    )
    raise HTTPException(status_code=400, detail="Invalid or expired OTP")
