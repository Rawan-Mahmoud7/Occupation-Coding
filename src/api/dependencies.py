"""
API Dependencies Module.
Provides FastAPI dependency injectors for CodingPipeline, database sessions, and configuration.
"""

from typing import AsyncGenerator, Optional
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from config import Settings, get_settings
from Service.pipeline.coding_pipeline import CodingPipeline


def get_pipeline(request: Request) -> CodingPipeline:
    """Injects the initialized CodingPipeline instance."""
    return request.app.state.pipeline


async def get_db_session(request: Request) -> AsyncGenerator[Optional[AsyncSession], None]:
    """Injects an async database session for health checks or admin routes."""
    session_factory = getattr(request.app.state, "session_factory", None)
    if session_factory:
        async with session_factory() as session:
            yield session
    else:
        yield None


def get_settings_dep() -> Settings:
    """Injects the central application configuration."""
    return get_settings()
