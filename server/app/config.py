from __future__ import annotations


from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic import Field, HttpUrl, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    api_key: str = Field(..., alias="API_KEY")
    redis_url: str = Field("redis://localhost:6379/0", alias="REDIS_URL")
    base_public_url: HttpUrl = Field("http://localhost:8000", alias="BASE_PUBLIC_URL")
    storage_backend: str = Field("local", alias="STORAGE_BACKEND")
    storage_local_root: Path = Field(Path("storage"), alias="STORAGE_LOCAL_ROOT")
    signed_url_ttl_seconds: int = Field(900, alias="SIGNED_URL_TTL_SECONDS")
    rate_limit_per_minute: int = Field(60, alias="RATE_LIMIT_PER_MINUTE")
    allowed_domains: List[str] = Field(default_factory=list, alias="ALLOWED_DOMAINS")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    @field_validator("allowed_domains", mode="before")
    @classmethod
    def _split_domains(cls, value: str | List[str] | None) -> List[str]:
        if value in (None, ""):
            return []
        if isinstance(value, list):
            return [v.strip().lower() for v in value if v.strip()]
        return [part.strip().lower() for part in str(value).split(",") if part.strip()]

    @property
    def normalized_storage_backend(self) -> str:
        value = self.storage_backend.lower()
        aliases = {
            "loc_wisso": "local",
            "filesystem": "local",
        }
        return aliases.get(value, value)


@lru_cache
def get_settings() -> Settings:
    return Settings()


def get_storage_root(settings: Settings) -> Path:
    root = settings.storage_local_root
    return root if root.is_absolute() else Path.cwd() / root
