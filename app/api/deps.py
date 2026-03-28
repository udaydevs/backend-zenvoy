from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from bson import ObjectId
from app.core.config import settings
from motor.motor_asyncio import AsyncIOMotorClient
from app.core.security import decode_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

async def get_db():
    client = AsyncIOMotorClient(settings.MONGODB_URL)
    return client[settings.DATABASE_NAME]

async def get_current_user(token: str = Depends(oauth2_scheme), db = Depends(get_db)) -> dict:
    user_id = decode_token(token)
    try:
        obj_id = ObjectId(user_id)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token subject format",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    user = await db["users"].find_one({"_id": obj_id})
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return {
        "user_id": str(user["_id"]),
        "first_name": user["first_name"],
        "last_name": user["last_name"],
        "username": user["username"],
        "phone_number": user["phone_number"],
        "emergency_phone": user.get("emergency_phone")
    }
