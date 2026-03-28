"""
Zenvoy backend ASGI application entrypoint.

Holds the core FastAPI initialization logic alongside application lifecycle
managers (for connecting to Beanie and loading the routing graph context).
"""

import os
import json
import logging
import asyncio
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


async def seed_crime_data():
    """
    Pre-populate the database with crime reports if empty.
    """
    count = await CrimeReport.count()
    if count > 10:
        logger.info(f"CrimeReport collection already has {count} records. Skipping seed.")
        return
    logger.info("Seeding crime data into MongoDB...")
    try:
        with open("app/data/crime_data.json", "r") as f:
            crimes = json.load(f)
        crime_docs = [CrimeReport(**crime) for crime in crimes]
        await CrimeReport.insert_many(crime_docs)

        logger.info(f"Seeded {len(crime_docs)} crime records successfully.")

    except Exception as e:
        logger.error(f"Failed to seed crime data: {e}")

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

    # Seed mock data if needed
    await seed_crime_data()

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
