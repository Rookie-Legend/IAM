from app.core.config import settings
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import List, Dict
from app.core.database import get_database
from app.api.dependencies import get_current_user
from app.models.user import UserInDB
from app.services.admin_chatbot import admin_chat
from app.services.user_chatbot import user_chat, extract_user_intent

router = APIRouter(prefix="/api/chatbot", tags=["Chatbot"])

ADMIN_ROLES = ["Security Admin", "System Administrator", "HR Manager", "admin"]

# Keywords that suggest the admin is making a personal VPN/access request for themselves
_ACCESS_KEYWORDS = [
    "want access", "request access", "need access", "give me access",
    "want vpn", "request vpn", "need vpn", "vpn access", "access to vpn",
    "can i get", "can i have", "i need", "i want",
]

class ChatQueryRequest(BaseModel):
    query: str
    history: List[Dict[str, str]] = []

@router.post("/query")
async def chat_query(request: ChatQueryRequest, db=Depends(get_database), current_user: UserInDB = Depends(get_current_user)):
    api_key = settings.GROQ_API_KEY
    if not api_key:
        return {"response": "⚠️ Groq API key not configured."}
    try:
        if current_user.role in ADMIN_ROLES:
            # If the message looks like a personal VPN/access request, run it through the
            # same user decision pipeline (ACCEPT/DENY/ESCALATE) instead of admin_chat.
            msg_lower = request.query.lower()
            might_be_access = any(kw in msg_lower for kw in _ACCESS_KEYWORDS)
            if might_be_access:
                user_intent = await extract_user_intent(request.query, request.history, db)
                if user_intent.get("intent") == "access_request":
                    response_text, _ = await user_chat(request.query, request.history, current_user, db)
                    return {"response": response_text}
            # All other admin messages go through the admin pipeline
            response_text, _ = await admin_chat(request.query, request.history, db, current_user.role)
        else:
            response_text, _ = await user_chat(request.query, request.history, current_user, db)
        return {"response": response_text}
    except Exception as e:
        return {"response": f"❌ AI error: {str(e)}"}
