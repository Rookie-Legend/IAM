from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.core.database import connect_to_mongo, close_mongo_connection

from app.api import auth, users, jml, policies, orchestrator, vpn, mfa, audit, admin, chatbot

app = FastAPI(title=settings.PROJECT_NAME)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://10.35.156.201:5173", "http://127.0.0.1:5173", "http://localhost:3000","http://125.10.0.1:5173"],
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

@app.get("/")
async def root():
    return {"status": "ok", "project": settings.PROJECT_NAME}

# Routers will be included here
