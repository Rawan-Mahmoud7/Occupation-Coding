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
    APP_NAME: str = "Egyptian Occupation Coding API"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    ENVIRONMENT: str = "production"
    LOG_LEVEL: str = "INFO"

    # ── PostgreSQL & pgvector Database Settings ──
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USERNAME: str = "postgres"
    POSTGRES_PASSWORD: str = Field(default="postgres", description="PostgreSQL password")
    POSTGRES_MAIN_DATABASE: str = "occupation_coding"
    POSTGRES_POOL_SIZE: int = 20
    POSTGRES_MAX_OVERFLOW: int = 10
    POSTGRES_POOL_TIMEOUT: float = 30.0

    # ── Voyage AI Embedder Settings ──
    VOYAGE_API_KEY: str = Field(default="", description="Primary Voyage AI API key")
    VOYAGE_MODEL: str = "voyage-context-4"
    VOYAGE_DIMENSION: int = 1024
    VOYAGE_RPM_LIMIT: int = 3
    VOYAGE_TPM_LIMIT: int = 10000
    VOYAGE_TIMEOUT_SECONDS: float = 20.0
    VOYAGE_MAX_RETRIES: int = 3

    # ── Remote LLM API & Multi-Account Rotation Settings ──
    LLM_PROVIDER: str = "remote_api"
    LLM_BASE_URL: str = "https://api.openai.com/v1"
    LLM_MODEL: str = "gemma2-9b-it"
    LLM_API_KEYS: str = Field(default="", description="Comma-separated API keys for rotation")
    LLM_CONCURRENCY: int = 4
    LLM_TIMEOUT_SECONDS: float = 35.0
    LLM_TEMPERATURE: float = 0.0
    LLM_MONTHLY_TOKEN_QUOTA_PER_KEY: int = 1000000

    # ── Cache & In-Flight Deduplication Settings ──
    SEMANTIC_CACHE_THRESHOLD: float = 0.98
    SEMANTIC_INFLIGHT_THRESHOLD: float = 0.98
    CACHE_MAX_SIZE: int = 50000
    INFLIGHT_TIMEOUT_SECONDS: float = 40.0

    # ── Pipeline Tuning Parameters ──
    RETRIEVAL_TOP_K: int = 20
    DEFAULT_BATCH_SIZE: int = 50

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
