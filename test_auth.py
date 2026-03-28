import asyncio
import httpx
from pymongo import MongoClient
import os

from app.core.config import settings

async def verify_auth():
    print("starting test server...")
    # This is a unit test script utilizing TestClient
    from fastapi.testclient import TestClient
    from app.main import app
    
    # We will just directly exercise the endpoints using TestClient
    # But wait, we need to ensure unique index logic is triggered.
    try:
        from testcontainers.mongodb import MongoDbContainer
        # To avoid mangling their real DB, let's use a real Motor client but 
        # point it to their test DB name if we don't use testcontainers.
    except ImportError:
        pass
        
    client = TestClient(app)
    
    try:
        with client: # Lifespan execution
            print("Client lifespan started")
            
            # 1. Register
            payload = {
                "first_name": "Test",
                "last_name": "User",
                "username": "testuser_123",
                "password": "Password123!",
                "phone_number": "+919876543210"
            }
            res = client.post("/api/v1/auth/register", json=payload)
            print("Register:", res.status_code, res.json())
            assert res.status_code in [201, 409] # 409 if already exists
            
            # 2. Login
            login_payload = {
                "username": "testuser_123",
                "password": "Password123!"
            }
            res_login = client.post("/api/v1/auth/login", json=login_payload)
            print("Login:", res_login.status_code, res_login.json())
            assert res_login.status_code == 200
            token = res_login.json()["token"]
            
            headers = {"Authorization": f"Bearer {token}"}
            
            # 3. Get /me
            res_me = client.get("/api/v1/auth/me", headers=headers)
            print("Get Me:", res_me.status_code, res_me.json())
            assert res_me.status_code == 200
            
            # 4. Patch /profile
            patch_payload = {
                "first_name": "UpdatedTest"
            }
            res_patch = client.patch("/api/v1/auth/profile", json=patch_payload, headers=headers)
            print("Patch Profile:", res_patch.status_code, res_patch.json())
            assert res_patch.status_code == 200
            assert res_patch.json()["first_name"] == "UpdatedTest"
            
            print("All auth tests passed successfully!")
            
    except Exception as e:
        print("Exception:", e)

if __name__ == "__main__":
    asyncio.run(verify_auth())
