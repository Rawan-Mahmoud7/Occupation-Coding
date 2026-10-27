from pathlib import Path
"""
Application Configuration Module.
Loads and validates all settings from environment variables (.env) using Pydantic Settings.
"""

from functools import lru_cache
from typing import List
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Central application configuration.
    All credentials and environment-specific parameters are read from .env.
    """
    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).resolve().parent / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore"
    )

    # ── General Application Settings ──
    APP_NAME: str
    APP_VERSION: str
    DEBUG: bool 
    ENVIRONMENT: str 
    LOG_LEVEL: str 

    # ── PostgreSQL & pgvector Database Settings ──
    POSTGRES_HOST: str
    POSTGRES_PORT: int
    POSTGRES_USERNAME: str
    POSTGRES_PASSWORD: str
    POSTGRES_MAIN_DATABASE: str
    POSTGRES_POOL_SIZE: int
    POSTGRES_MAX_OVERFLOW: int
    POSTGRES_POOL_TIMEOUT: float

    # ── Voyage AI Embedder Settings ──
    VOYAGE_API_KEY: str
    VOYAGE_MODEL: str
    VOYAGE_DIMENSION: int
    VOYAGE_RPM_LIMIT: int 
    VOYAGE_TPM_LIMIT: int
    VOYAGE_TIMEOUT_SECONDS: float 
    VOYAGE_MAX_RETRIES: int 

    # ── Remote LLM API & Multi-Account Rotation Settings ──
    LLM_PROVIDER: str
    LLM_BASE_URL: str
    LLM_MODEL: str 
    LLM_API_KEYS: str
    LLM_CONCURRENCY: int 
    LLM_TIMEOUT_SECONDS: float
    LLM_TEMPERATURE: float
    LLM_MONTHLY_TOKEN_QUOTA_PER_KEY: int

    # ── Cache & In-Flight Deduplication Settings ──
    SEMANTIC_CACHE_THRESHOLD: float
    SEMANTIC_INFLIGHT_THRESHOLD: float 
    CACHE_MAX_SIZE: int
    INFLIGHT_TIMEOUT_SECONDS: float 

    # ── Pipeline Tuning Parameters ──
    RETRIEVAL_TOP_K: int 
    DEFAULT_BATCH_SIZE: int

    @property
    def api_keys_list(self) -> List[str]:
        """Returns the list of configured LLM API keys for round-robin / quota rotation."""
        return [k.strip() for k in self.LLM_API_KEYS.split(",") if k.strip()]

    @property
    def async_database_url(self) -> str:
        """Constructs the asyncpg connection string for SQLAlchemy async engine."""
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USERNAME}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_MAIN_DATABASE}"
        )


@lru_cache()
def get_settings() -> Settings:
    """Returns a cached singleton instance of the Settings."""
    return Settings()
