from typing import Optional
from pydantic import BaseModel, Field

class UserRegisterRequest(BaseModel):
    first_name: str
    last_name: str
    username: str
    password: str = Field(..., min_length=8)
    phone_number: str
    emergency_phone: Optional[str] = None

class UserLoginRequest(BaseModel):
    username: str
    password: str

class UserProfileUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone_number: Optional[str] = None
    emergency_phone: Optional[str] = None
