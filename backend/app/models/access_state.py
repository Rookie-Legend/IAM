from pydantic import BaseModel, Field
from typing import List

class AccessStateBase(BaseModel):
    vpn_access: List[str] = []

class AccessStateInDB(AccessStateBase):
    user_id: str = Field(alias="_id")

    class Config:
        populate_by_name = True
