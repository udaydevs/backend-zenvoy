"""
Database initialization module for Beanie and Motor.

This handles the connection configuration and model binding.
"""
from typing import Any, cast
from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie

from app.core.config import settings
from app.models.crime import CrimeReport
from app.models.route_cache import CachedRoute


async def init_db():
    """
    Initialize the MongoDB connection and Beanie ODM models.

    This binds the given `document_models` to the active Motor client instance 
    so they can be queried globally.
    """
    client = AsyncIOMotorClient(settings.MONGODB_URL)
    database = client[settings.DATABASE_NAME]

    await init_beanie(
        database=cast(Any, database),
        document_models=[CrimeReport, CachedRoute]
    )
