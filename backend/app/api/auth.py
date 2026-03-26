from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from datetime import datetime, timedelta
import random
import string
from app.core.database import get_database
from app.core.security import verify_password, create_access_token, get_password_hash
from app.models.user import UserCreate
from app.services.email_service import send_email

router = APIRouter(prefix="/api/auth", tags=["Auth"])

@router.post("/login")
async def login(form_data: OAuth2PasswordRequestForm = Depends(), db=Depends(get_database)):
    user = await db["users"].find_one({"username": form_data.username})
    if not user:
        user = await db["users"].find_one({"email": form_data.username})
    if not user or not verify_password(form_data.password, user.get("hashed_password", "")):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect credentials")
    if user.get("disabled", False):
        raise HTTPException(status_code=400, detail="Account is disabled")
    token = create_access_token({"sub": user["_id"]})
    return {"access_token": token, "token_type": "bearer", "role": user.get("role"), "user_id": user["_id"]}

@router.post("/register")
async def register(user_in: UserCreate, db=Depends(get_database)):
    existing = await db["users"].find_one({"$or": [{"username": user_in.username}, {"email": user_in.email}]})
    if existing:
        raise HTTPException(status_code=400, detail="Username or email already exists")
    hashed = get_password_hash(user_in.password)
    user_dict = user_in.model_dump(exclude={"password"})
    user_dict["_id"] = user_in.username
    user_dict["hashed_password"] = hashed
    await db["users"].insert_one(user_dict)
    await db["access_states"].insert_one({"_id": user_dict["_id"], "vpn_access": []})
    return {"status": "success", "message": "User registered successfully"}

class VerifyTokenRequest(BaseModel):
    token: str

class VerifyOTPRequest(BaseModel):
    token: str
    otp: str

class CompleteRegistrationRequest(BaseModel):
    token: str
    username: str
    full_name: str
    password: str

@router.post("/verify-invite-token")
async def verify_invite_token(request: VerifyTokenRequest, db=Depends(get_database)):
    invite = await db["invites"].find_one({"token": request.token, "status": "pending"})
    if not invite:
        raise HTTPException(status_code=400, detail="Invalid or expired invite token")
    if invite["expires_at"] < datetime.utcnow():
        await db["invites"].update_one({"token": request.token}, {"$set": {"status": "expired"}})
        raise HTTPException(status_code=400, detail="Invite token has expired")

    return {"email": invite["email"], "role": invite["role"], "department": invite["department"]}

@router.post("/request-registration-otp")
async def request_registration_otp(request: VerifyTokenRequest, db=Depends(get_database)):
    invite = await db["invites"].find_one({"token": request.token, "status": "pending"})
    if not invite or invite["expires_at"] < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Invalid or expired invite token")

    email = invite["email"]
    otp = ''.join(random.choices(string.digits, k=6))
    expires_at = datetime.utcnow() + timedelta(minutes=10)

    await db["otp_store"].update_one(
        {"user_id": f"invite_{request.token}"},
        {"$set": {"otp": otp, "email": email, "expires_at": expires_at, "verified": False, "token": request.token}},
        upsert=True
    )

    await send_email(email, "Your CorpOD Verification Code", "otp_email.html", {"OTP": otp})

    return {"status": "success", "message": f"OTP sent to {email}"}

@router.post("/verify-registration-otp")
async def verify_registration_otp(request: VerifyOTPRequest, db=Depends(get_database)):
    invite = await db["invites"].find_one({"token": request.token, "status": "pending"})
    if not invite or invite["expires_at"] < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Invalid or expired invite token")

    record = await db["otp_store"].find_one({"user_id": f"invite_{request.token}", "otp": request.otp, "verified": False})
    if not record or record["expires_at"] < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Invalid or expired OTP")

    await db["otp_store"].update_one({"user_id": f"invite_{request.token}"}, {"$set": {"verified": True}})
    await db["invites"].update_one({"token": request.token}, {"$set": {"status": "otp_verified"}})

    return {"status": "success", "message": "OTP verified. You can now complete your registration."}

@router.post("/complete-registration")
async def complete_registration(request: CompleteRegistrationRequest, db=Depends(get_database)):
    invite = await db["invites"].find_one({"token": request.token, "status": "otp_verified"})
    if not invite:
        raise HTTPException(status_code=400, detail="Invalid or expired invite token or OTP not verified")

    otp_record = await db["otp_store"].find_one({"user_id": f"invite_{request.token}", "verified": True})
    if not otp_record:
        raise HTTPException(status_code=400, detail="OTP not verified. Please complete OTP verification first.")

    existing = await db["users"].find_one({"$or": [{"username": request.username}, {"email": invite["email"]}]})
    if existing:
        raise HTTPException(status_code=400, detail="Username already exists")

    hashed = get_password_hash(request.password)
    user_dict = {
        "_id": request.username,
        "username": request.username,
        "email": invite["email"],
        "full_name": request.full_name,
        "department": invite["department"],
        "role": invite["role"],
        "status": "active",
        "disabled": False,
        "hashed_password": hashed
    }
    await db["users"].insert_one(user_dict)
    await db["access_states"].insert_one({"_id": request.username, "vpn_access": []})

    await db["invites"].update_one({"token": request.token}, {"$set": {"status": "completed"}})
    await db["otp_store"].delete_one({"user_id": f"invite_{request.token}"})

    return {"status": "success", "message": "Registration completed successfully. You can now login."}