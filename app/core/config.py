"""
Configuration management for the Zenvoy application.

This module defines the environment configurations required for the backend
infrastructure, database, and third-party services like Twilio.
"""
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parents[2]

class Settings(BaseSettings):
    """
    Application settings object containing environmental variables.
    
    Includes MongoDB setup, Twilio authentication, and GraphML path settings.
    """
    model_config = SettingsConfigDict(
        env_file=BASE_DIR/'.env',
        env_ignore_empty=True,
        extra="ignore",
    )
    MONGODB_URL: str
    DATABASE_NAME: str

    TWILIO_ACCOUNT_SID: str
    TWILIO_AUTH_TOKEN: str
    TWILIO_FROM_NUMBER: str

    MAPILLARY_TOKEN: str

    NEWSAPI_KEY: str
    GEMINI_API_KEY: str
    GRAPH_PATH: str = "app/data/delhi_walk.graphml"


settings = Settings()
