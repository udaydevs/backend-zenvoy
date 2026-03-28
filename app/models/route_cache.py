"""
MongoDB collection models for representing cached and pre-computed routes.
"""

from datetime import datetime
from typing import List, Dict, Any
from beanie import Document
from pydantic import Field


class CachedRoute(Document):
    """
    Beanie Model representing a previously successfully calculated safety route.
    """
    route_type: str  # "fast" or "safe"
    origin: str  # Could be a string like "lat,lng"
    destination: str  # Could be a string like "lat,lng"
    coordinates: List[List[float]]
    score_breakdown: Dict[str, Any]
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "cached_routes"
