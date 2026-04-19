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
from app.services.gitlab_sync import ensure_gitlab_user, update_gitlab_password

router = APIRouter(prefix="/api/auth", tags=["Auth"])

DEPT_PREFIX_MAP = {
    "engineering": "U", "devops": "D", "sre": "D", "infrastructure": "D",
    "finance": "F", "financial": "F", "hr": "H", "human_resources": "H",
    "product": "P", "security": "S", "legal": "L", "marketing": "M", "sales": "S",
}


async def generate_user_id(db, department: str) -> str:
    prefix = DEPT_PREFIX_MAP.get(department.lower(), "U")
    users = await db["users"].find({}, {"user_id": 1}).to_list(length=None)
    existing = []
    for u in users:
        uid = u.get("user_id")
        if uid and uid.startswith(prefix):
            try:
                num = int(uid[len(prefix):])
                existing.append(num)
            except ValueError:
                pass
    next_num = (max(existing) + 1) if existing else 1001
    return f"{prefix}{next_num}"

@router.post("/login")
async def login(form_data: OAuth2PasswordRequestForm = Depends(), db=Depends(get_database)):
    user = await db["users"].find_one({"username": form_data.username})
    if not user:
        user = await db["users"].find_one({"email": form_data.username})
    if not user or not verify_password(form_data.password, user.get("hashed_password", "")):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect credentials")
    if user.get("disabled", False):
        raise HTTPException(status_code=400, detail="Account is disabled")
    token = create_access_token({"sub": user.get("user_id", user["_id"])})
    return {"access_token": token, "token_type": "bearer", "role": user.get("role"), "user_id": user.get("user_id", user["_id"])}

@router.post("/register")
async def register(user_in: UserCreate, db=Depends(get_database)):
    existing = await db["users"].find_one({"$or": [{"username": user_in.username}, {"email": user_in.email}]})
    if existing:
        raise HTTPException(status_code=400, detail="Username or email already exists")
    hashed = get_password_hash(user_in.password)
    user_dict = user_in.model_dump(exclude={"password"})
    user_dict["user_id"] = await generate_user_id(db, user_in.department)
    user_dict["hashed_password"] = hashed
    await db["users"].insert_one(user_dict)
    gitlab_sync = await ensure_gitlab_user(user_dict, user_in.password)
    await db["access_states"].insert_one({
        "user_id": user_dict["user_id"],
        "vpn_access": [],
        "connected": False,
        "connected_vpn": None,
        "connected_ip": None,
        "connected_at": None,
        "last_disconnected_at": None
    })
    return {
        "status": "success",
        "message": "User registered successfully",
        "gitlab_sync": gitlab_sync.as_dict(),
    }

class VerifyTokenRequest(BaseModel):
    token: str

class VerifyOTPRequest(BaseModel):
    token: str
    otp: str

class PasswordResetRequest(BaseModel):
    identifier: str

class VerifyPasswordResetOTPRequest(BaseModel):
    identifier: str
    otp: str

class CompletePasswordResetRequest(BaseModel):
    identifier: str
    otp: str
    password: str

class CompleteRegistrationRequest(BaseModel):
    token: str
    username: str
    full_name: str
    password: str


def mask_email(email: str) -> str:
    if not email or "@" not in email:
        return ""
    user, domain = email.split("@", 1)
    if len(user) <= 2:
        masked_user = user[:1] + "***"
    else:
        masked_user = user[:2] + "***" + user[-1:]
    return f"{masked_user}@{domain}"


async def find_reset_user(db, identifier: str):
    normalized = (identifier or "").strip()
    if not normalized:
        return None
    return await db["users"].find_one({
        "$or": [
            {"username": normalized},
            {"email": normalized},
            {"user_id": normalized},
        ],
        "disabled": {"$ne": True},
    })


def reset_otp_key(user_id: str) -> str:
    return f"reset_{user_id}"

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


@router.post("/password-reset/request-otp")
async def request_password_reset_otp(request: PasswordResetRequest, db=Depends(get_database)):
    user = await find_reset_user(db, request.identifier)
    if not user:
        raise HTTPException(status_code=404, detail="No active account found for that username or email")

    email = user.get("email")
    if not email:
        raise HTTPException(status_code=400, detail="No email is configured for this account")

    otp = ''.join(random.choices(string.digits, k=6))
    expires_at = datetime.utcnow() + timedelta(minutes=10)
    await db["otp_store"].update_one(
        {"user_id": reset_otp_key(user["user_id"])},
        {
            "$set": {
                "otp": otp,
                "email": email,
                "expires_at": expires_at,
                "verified": False,
                "purpose": "password_reset",
                "identifier": request.identifier.strip(),
            }
        },
        upsert=True,
    )

    await send_email(email, "Your CorpOD Password Reset Code", "otp_email.html", {"OTP": otp})
    return {"status": "success", "message": "OTP sent", "email": mask_email(email)}


@router.post("/password-reset/verify-otp")
async def verify_password_reset_otp(request: VerifyPasswordResetOTPRequest, db=Depends(get_database)):
    user = await find_reset_user(db, request.identifier)
    if not user:
        raise HTTPException(status_code=404, detail="No active account found for that username or email")

    record = await db["otp_store"].find_one({
        "user_id": reset_otp_key(user["user_id"]),
        "otp": request.otp,
        "verified": False,
        "purpose": "password_reset",
    })
    if not record or record["expires_at"] < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Invalid or expired OTP")

    await db["otp_store"].update_one(
        {"user_id": reset_otp_key(user["user_id"])},
        {"$set": {"verified": True}},
    )
    return {"status": "success", "message": "OTP verified"}


@router.post("/password-reset/complete")
async def complete_password_reset(request: CompletePasswordResetRequest, db=Depends(get_database)):
    if len(request.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

    user = await find_reset_user(db, request.identifier)
    if not user:
        raise HTTPException(status_code=404, detail="No active account found for that username or email")

    record = await db["otp_store"].find_one({
        "user_id": reset_otp_key(user["user_id"]),
        "otp": request.otp,
        "verified": True,
        "purpose": "password_reset",
    })
    if not record or record["expires_at"] < datetime.utcnow():
        raise HTTPException(status_code=400, detail="OTP not verified or expired")

    await db["users"].update_one(
        {"user_id": user["user_id"]},
        {"$set": {
            "hashed_password": get_password_hash(request.password),
            "gitlab_temp_password_set": False,
        }},
    )
    gitlab_sync = await update_gitlab_password(user, request.password)
    await db["otp_store"].delete_one({"user_id": reset_otp_key(user["user_id"])})
    return {
        "status": "success",
        "message": "Password reset successfully",
        "gitlab_sync": gitlab_sync.as_dict(),
    }


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
    new_user_id = await generate_user_id(db, invite.get("department", "engineering"))
    user_dict = {
        "user_id": new_user_id,
        "username": request.username,
        "email": invite["email"],
        "full_name": request.full_name,
        "department": invite["department"],
        "role": invite["role"],
        "status": "inactive",
        "disabled": False,
        "hashed_password": hashed
    }
    await db["users"].insert_one(user_dict)
    gitlab_sync = await ensure_gitlab_user(user_dict, request.password)
    await db["access_states"].insert_one({
        "user_id": new_user_id,
        "vpn_access": [],
        "connected": False,
        "connected_vpn": None,
        "connected_ip": None,
        "connected_at": None,
        "last_disconnected_at": None
    })

    await db["invites"].update_one({"token": request.token}, {"$set": {"status": "completed"}})
    await db["otp_store"].delete_one({"user_id": f"invite_{request.token}"})

    return {
        "status": "success",
        "message": "Registration completed successfully. You can now login.",
        "gitlab_sync": gitlab_sync.as_dict(),
    }
