from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://clipfactory:clipfactory@localhost:5432/clipfactory"
    redis_url: str = "redis://localhost:6379/0"
    storage_path: Path = Path("storage")
    worker_max_retries: int = 3
    worker_job_lease_seconds: int = 30
    worker_heartbeat_seconds: int = 10
    ingest_max_height: int = 720
    min_source_duration_seconds: float = 30
    openai_scoring_model: str = "gpt-5.6-sol"
    openai_transcription_model: str = "whisper-1"
    cors_origins: str = "http://localhost:3000"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
