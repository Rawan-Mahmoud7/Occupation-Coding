"""
Main Application Entry Point.
Configures FastAPI lifespan, CORS, database engine, dynamic section prompt loading, and router mounting.
"""

import os
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from config import get_settings
from api.router import router as api_router
from Service.prompts.coding_prompts import load_sections_prompt_from_db
from Service.pipeline.service_registry import build_default_registry
from Service.pipeline.coding_pipeline import CodingPipeline

# Ensure logs directory exists
LOGS_DIR = Path(__file__).resolve().parent.parent / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOGS_DIR / "app.log"

# Detailed Formatter supporting Arabic and timestamps
log_formatter = logging.Formatter(
    "%(asctime)s [%(levelname)s] [%(name)s]: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

# 1. Console Handler (stdout)
console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)

# 2. Rotating File Handler (UTF-8 encoded)
file_handler = RotatingFileHandler(
    LOG_FILE,
    maxBytes=15 * 1024 * 1024,  # 15 MB
    backupCount=5,
    encoding="utf-8",
)
file_handler.setFormatter(log_formatter)

# Configure Root Logger
root_logger = logging.getLogger()
root_logger.setLevel(logging.DEBUG)
root_logger.addHandler(console_handler)
root_logger.addHandler(file_handler)

# Suppress overly verbose third-party loggers
logging.getLogger("uvicorn.access").setLevel(logging.INFO)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.INFO)
logging.getLogger("voyage").setLevel(logging.INFO)

log = logging.getLogger("main")
log.info(f"Logging initialized. Output file: {LOG_FILE}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manages application startup and clean graceful shutdown."""
    settings = get_settings()
    log.info(f"Starting {settings.APP_NAME} v{settings.APP_VERSION}...")

    # 1. Initialize Async PostgreSQL Engine & Session Factory
    engine = create_async_engine(
        settings.async_database_url,
        pool_size=settings.POSTGRES_POOL_SIZE,
        max_overflow=settings.POSTGRES_MAX_OVERFLOW,
        pool_timeout=settings.POSTGRES_POOL_TIMEOUT,
    )
    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    # 2. Dynamic Section Prompts loading from PostgreSQL
    try:
        await load_sections_prompt_from_db(session_factory)
        log.info("Loaded official section descriptions dynamically from database.")
    except Exception as exc:
        log.warning(f"Could not load sections dynamically from DB, using official defaults: {exc}")

    # 3. Construct Service Registry and Coding Pipeline
    registry = build_default_registry(settings, session_factory)
    pipeline = CodingPipeline(registry, settings)

    # Store shared instances on app state
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.registry = registry
    app.state.pipeline = pipeline

    log.info("Application initialized and ready to receive requests.")
    yield

    # Graceful Shutdown
    log.info("Shutting down application...")
    if hasattr(registry.embedder, "close"):
        await registry.embedder.close()
    await engine.dispose()
    log.info("Shutdown completed.")


app = FastAPI(
    title="Egyptian Occupation Coding API",
    version="1.0.0",
    description="Automated AI-powered occupation coding system conforming to Egyptian Standard Classification 2017 & ISCO-08.",
    lifespan=lifespan,
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount REST API Router
app.include_router(api_router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
