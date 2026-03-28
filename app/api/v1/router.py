"""
Main API router aggregator for API v1.
"""
from fastapi import APIRouter
from app.api.v1.routes import router as routes_router
from app.api.v1.sos import router as sos_router
from app.api.v1.demo import router as demo_router

from app.api.v1.auth import router as auth_router

api_router = APIRouter()

api_router.include_router(routes_router, tags=["routing"])
api_router.include_router(sos_router, tags=["sos"])
api_router.include_router(demo_router, tags=["demo"])
api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
