from pydantic_settings import BaseSettings
from typing import Optional
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_DIR.parent

class Settings(BaseSettings):
    PROJECT_NAME: str = "CorpOD IAM Orchestrator"
    MONGO_URL: str = "mongodb://localhost:27017"
    DB_NAME: str = "iam_db"
    SECRET_KEY: str = "change-me-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    GROQ_API_KEY: Optional[str] = None
    VPN_SERVER_URL: str = "http://vpn-server:4000"
    FRONTEND_URL: str = "http://localhost:5173"
    GITLAB_URL: str = "http://172.30.0.50"
    GITLAB_ADMIN_TOKEN: str = ""
    GITLAB_SYNC_ENABLED: bool = False

    class Config:
        env_file = (REPO_ROOT / ".env", BACKEND_DIR / ".env")
        extra = "allow"

settings = Settings()
