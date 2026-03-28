from pydantic import BaseModel, EmailStr, Field
from typing import Optional

class UserBase(BaseModel):
    username: str
    email: EmailStr
    full_name: str
    department: str
    role: str
    status: str = "active"
    disabled: bool = False

class UserCreate(UserBase):
    password: str

class UserInDB(UserBase):
    user_id: str = Field(alias="user_id")

    class Config:
        populate_by_name = True
