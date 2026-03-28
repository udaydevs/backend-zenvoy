from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from bson import ObjectId

from app.models.user import UserRegisterRequest, UserLoginRequest, UserProfileUpdate
from app.core.security import get_password_hash, verify_password, create_access_token
from app.api.deps import get_db, get_current_user

router = APIRouter()

@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(user: UserRegisterRequest, db = Depends(get_db)):
    username_lower = user.username.lower().strip()
    
    existing = await db["users"].find_one({"username": username_lower})
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username already exists"
        )
    
    hashed_password = get_password_hash(user.password)
    
    new_user = {
        "first_name": user.first_name,
        "last_name": user.last_name,
        "username": username_lower,
        "password_hash": hashed_password,
        "phone_number": user.phone_number,
        "emergency_phone": user.emergency_phone,
        "created_at": datetime.now(timezone.utc)
    }
    
    result = await db["users"].insert_one(new_user)
    
    return {
        "user_id": str(result.inserted_id),
        "username": username_lower,
        "message": "Account created successfully"
    }

@router.post("/login", status_code=status.HTTP_200_OK)
async def login(credentials: UserLoginRequest, db = Depends(get_db)):
    username_lower = credentials.username.lower().strip()
    
    user = await db["users"].find_one({"username": username_lower})
    if not user or not verify_password(credentials.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Username not found or password does not match"
        )
    
    user_id_str = str(user["_id"])
    token = create_access_token(user_id_str)
    
    return {
        "token": token,
        "user": {
            "user_id": user_id_str,
            "first_name": user["first_name"],
            "last_name": user["last_name"],
            "username": user["username"],
            "phone_number": user["phone_number"],
            "emergency_phone": user.get("emergency_phone")
        }
    }

@router.get("/me", status_code=status.HTTP_200_OK)
async def get_me(current_user: dict = Depends(get_current_user)):
    return current_user

@router.patch("/profile", status_code=status.HTTP_200_OK)
async def update_profile(updates: UserProfileUpdate, current_user: dict = Depends(get_current_user), db = Depends(get_db)):
    try:
        update_data = updates.model_dump(exclude_unset=True)
    except AttributeError:
        update_data = updates.dict(exclude_unset=True)
        
    if not update_data:
        return current_user
        
    await db["users"].update_one(
        {"_id": ObjectId(current_user["user_id"])},
        {"$set": update_data}
    )
    
    current_user.update(update_data)
    return current_user
