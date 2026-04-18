import json
from datetime import datetime, timezone
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.core.config import settings
from app.core.database import connect_to_mongo, close_mongo_connection

from app.api import auth, users, jml, policies, orchestrator, vpn, mfa, audit, admin, chatbot, messaging


class UTCJSONEncoder(json.JSONEncoder):
    """Serialize naive datetimes as UTC by appending 'Z', preserving aware datetimes."""
    def default(self, obj):
        if isinstance(obj, datetime):
            if obj.tzinfo is None:
                # Treat naive datetimes as UTC and add Z
                return obj.strftime('%Y-%m-%dT%H:%M:%S.') + f'{obj.microsecond:06d}'[:3] + 'Z'
            return obj.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.') + f'{obj.microsecond:06d}'[:3] + 'Z'
        return super().default(obj)


class UTCJSONResponse(JSONResponse):
    def render(self, content) -> bytes:
        return json.dumps(content, cls=UTCJSONEncoder, ensure_ascii=False).encode('utf-8')


app = FastAPI(title=settings.PROJECT_NAME, default_response_class=UTCJSONResponse)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL, "http://127.0.0.1:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup_db_client():
    connect_to_mongo()

@app.on_event("shutdown")
async def shutdown_db_client():
    close_mongo_connection()

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(jml.router)
app.include_router(policies.router)
app.include_router(orchestrator.router)
app.include_router(vpn.router)
app.include_router(mfa.router)
app.include_router(audit.router)
app.include_router(admin.router)
app.include_router(chatbot.router)
app.include_router(messaging.router)

@app.get("/")
async def root():
    return {"status": "ok", "project": settings.PROJECT_NAME}

# Routers will be included here
