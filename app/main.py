"""
Zenvoy backend ASGI application entrypoint.

Holds the core FastAPI initialization logic alongside application lifecycle
managers (for connecting to Beanie and loading the routing graph context).
"""

import os
import json
import logging
import asyncio
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from app.services.crime_pipeline import process_daily_crimes

from app.core.config import settings
from app.core.db import init_db
from app.models.crime import CrimeReport
from app.api.v1.router import api_router
from app.services.routing import load_graph

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


CRIME_SEED_PATH = Path("app/data/crime_data.json")


def crime_seed_identity(crime: dict) -> dict:
    return {
        "lat": float(crime["lat"]),
        "lng": float(crime["lng"]),
        "type": str(crime["type"]),
        "severity": float(crime["severity"]),
        "description": str(crime["description"]),
    }


async def sync_crime_data():
    """
    Ensure MongoDB contains the seed crime dataset exactly once per seed record.
    """
    logger.info("Synchronizing crime data into MongoDB...")
    try:
        with CRIME_SEED_PATH.open("r", encoding="utf-8") as f:
            seed_crimes = json.load(f)

        normalized_seed_crimes = [crime_seed_identity(crime) for crime in seed_crimes]
        seed_keys = {
            (
                crime["lat"],
                crime["lng"],
                crime["type"],
                crime["severity"],
                crime["description"],
            )
            for crime in normalized_seed_crimes
        }

        from motor.motor_asyncio import AsyncIOMotorClient

        client = AsyncIOMotorClient(settings.MONGODB_URL)
        collection = client[settings.DATABASE_NAME][CrimeReport.Settings.name]
        existing_docs = await collection.find(
            {},
            {
                "_id": 1,
                "lat": 1,
                "lng": 1,
                "type": 1,
                "severity": 1,
                "description": 1,
            },
        ).to_list(None)

        seen_seed_docs = set()
        duplicate_ids = []
        for doc in existing_docs:
            identity = (
                float(doc.get("lat", 0.0)),
                float(doc.get("lng", 0.0)),
                str(doc.get("type", "")),
                float(doc.get("severity", 0.0)),
                str(doc.get("description", "")),
            )

            if identity not in seed_keys:
                continue

            if identity in seen_seed_docs:
                duplicate_ids.append(doc["_id"])
            else:
                seen_seed_docs.add(identity)

        if duplicate_ids:
            result = await collection.delete_many({"_id": {"$in": duplicate_ids}})
            logger.info("Removed %s duplicate seeded crime records.", result.deleted_count)

        missing_crimes = [
            crime
            for crime in normalized_seed_crimes
            if (
                crime["lat"],
                crime["lng"],
                crime["type"],
                crime["severity"],
                crime["description"],
            ) not in seen_seed_docs
        ]

        if missing_crimes:
            await CrimeReport.insert_many([CrimeReport(**crime) for crime in missing_crimes])
            logger.info("Inserted %s missing crime records.", len(missing_crimes))

        final_count = await CrimeReport.count()
        logger.info(
            "Crime sync complete. Seed records=%s, collection records=%s",
            len(normalized_seed_crimes),
            final_count,
        )
        client.close()
    except Exception as e:
        logger.error(f"Failed to synchronize crime data: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan context orchestrating setup and teardown tasks.
    """
    # Startup
    logger.info("Starting up Zenvoy backend...")

    # Init DB
    await init_db()
    
    # Create unique index on users.username
    try:
        from motor.motor_asyncio import AsyncIOMotorClient
        client = AsyncIOMotorClient(settings.MONGODB_URL)
        db = client[settings.DATABASE_NAME]
        await db["users"].create_index("username", unique=True)
        logger.info("Ensured unique index on users.username")
    except Exception as e:
        logger.error(f"Failed to create unique index on users.username: {e}")

    # Synchronize seed crime data before routing requests use it
    await sync_crime_data()

    # Load Route Graph
    graph_path = settings.GRAPH_PATH
    if os.path.exists(graph_path):
        app.state.graph = load_graph(graph_path)
    else:
        logger.warning("Graph file not found at %s. Routing might fail.", graph_path)
        app.state.graph = None

        
    # scheduler = AsyncIOScheduler()
    # # Fire once immediately so you can test without waiting
    # asyncio.create_task(process_daily_crimes())
    # # Keep daily schedule for production
    # scheduler.add_job(process_daily_crimes, CronTrigger(hour=2, minute=0, timezone="UTC"))
    # scheduler.start()
    # app.state.scheduler = scheduler
    yield

    # Shutdown
    if hasattr(app.state, "scheduler"):
        app.state.scheduler.shutdown()
    logger.info("Shutting down Zenvoy backend...")
    # Clean up resources if needed


app = FastAPI(
    title="Zenvoy API",
    description="Backend API for Zenvoy women's safety navigation app",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for hackathon demo
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API Router
app.include_router(api_router, prefix="/api/v1")


@app.get("/health")
async def health_check():
    """
    Standard network availability probe returning application state.
    """
    return {
        "status": "ok",
        "graph_loaded": getattr(app.state, "graph", None) is not None,
    }
