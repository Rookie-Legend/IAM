from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

class AuditLog(BaseModel):
    user_id: str
    action: str
    target_user: Optional[str] = None
    target_resource: Optional[str] = None
    mfa_status: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
