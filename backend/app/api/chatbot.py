from app.core.config import settings
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import List, Dict
from app.core.database import get_database
from app.api.dependencies import get_current_user
from app.models.user import UserInDB
from app.services.admin_chatbot import admin_chat
from app.services.user_chatbot import user_chat

router = APIRouter(prefix="/api/chatbot", tags=["Chatbot"])

ADMIN_ROLES = ["Security Admin", "System Administrator", "HR Manager", "admin"]

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
            response_text, _ = await admin_chat(request.query, request.history, db, current_user.role)
        else:
            response_text, _ = await user_chat(request.query, request.history, current_user, db)
        return {"response": response_text}
    except Exception as e:
        return {"response": f"❌ AI error: {str(e)}"}
