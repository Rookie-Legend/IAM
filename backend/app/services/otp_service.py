import random
import string
from datetime import datetime, timedelta
from app.services.email_service import send_email

class OTPService:
    async def generate_otp(self, user_id: str, email: str, db) -> str:
        otp = ''.join(random.choices(string.digits, k=6))
        expires_at = datetime.utcnow() + timedelta(minutes=10)
        await db["otp_store"].update_one(
            {"user_id": user_id},
            {"$set": {"otp": otp, "email": email, "expires_at": expires_at, "verified": False}},
            upsert=True
        )
        await send_email(email, "Your CorpOD Verification Code", "otp_email.html", {"OTP": otp})
        return otp

    async def verify_otp(self, user_id: str, otp: str, db) -> bool:
        record = await db["otp_store"].find_one({"user_id": user_id, "otp": otp, "verified": False})
        if record and record["expires_at"] > datetime.utcnow():
            await db["otp_store"].update_one({"user_id": user_id}, {"$set": {"verified": True}})
            return True
        return False

otp_service = OTPService()