from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum

class PolicyType(str, Enum):
    JML = "jml"
    ACCESS = "access"
    START_ACCESS = "start_access"
    BLOCK_ACCESS = "block_access"
    MFA = "mfa"

class PolicyBase(BaseModel):
    name: str
    type: PolicyType
    description: str
    department: str
    vpn: str
    is_active: bool = True

class PolicyCreate(PolicyBase):
    pass

class Policy(PolicyBase):
    pol_id: str = Field(alias="pol_id")
    created_on: datetime = Field(default_factory=datetime.utcnow)
    updated_on: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        populate_by_name = True

PolicyInDB = Policy
