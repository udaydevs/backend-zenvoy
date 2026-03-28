"""
MongoDB collection models for representing Crime Reports in Beanie.
"""
from datetime import datetime
from beanie import Document
from pydantic import Field


class CrimeReport(Document):
    """
    Detailed model representing a single crime or safety incident on the map.
    """
    lat: float
    lng: float
    type: str
    severity: float = Field(ge=0, le=1)
    description: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "crime_reports"
