from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime

class AccessStateBase(BaseModel):
    vpn_access: List[str] = []

class AccessStateInDB(AccessStateBase):
    user_id: str = Field(alias="user_id")
    has_provisioned: bool = False
    provisioned_vpn: Optional[str] = None
    connected: bool = False
    connected_vpn: Optional[str] = None
    connected_ip: Optional[str] = None
    connected_at: Optional[datetime] = None
    last_disconnected_at: Optional[datetime] = None

    class Config:
        populate_by_name = True
