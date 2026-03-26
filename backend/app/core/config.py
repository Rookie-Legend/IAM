from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    PROJECT_NAME: str = "CorpOD IAM Orchestrator"
    MONGO_URL: str = "mongodb://localhost:27017"
    DB_NAME: str = "iam_db"
    SECRET_KEY: str = "change-me-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    GROQ_API_KEY: Optional[str] = None
    VPN_SERVER_URL: str = "http://vpn-server:8000"

    class Config:
        env_file = ".env"
        extra = "allow"

settings = Settings()
