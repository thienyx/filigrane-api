from __future__ import annotations

import os
from functools import lru_cache
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class FiligraneSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FILIGRANE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: Literal["development", "staging", "production"] = "development"
    database_url: str | None = Field(default=None)
    log_level: str = Field(default="info")
    admin_token: str | None = Field(default=None)

    cors_origins: str = ""
    chrome_extension_ids: str = ""

    resend_api_key: str | None = None
    email_from: str = Field(default="noreply@example.com")
    public_app_url: str = Field(default="http://127.0.0.1:3000")
    api_public_url: str = Field(default="http://127.0.0.1:8000")

    session_cookie_secure: bool = True
    session_ttl_days: int = 30
    magic_link_ttl_minutes: int = 15

    openapi_enabled: bool = False

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_async_database_url(cls, value: str | None) -> str | None:
        if value is None or not isinstance(value, str):
            return value
        trimmed = value.strip()
        if not trimmed:
            return None
        if trimmed.startswith("postgresql+asyncpg://"):
            return trimmed
        if trimmed.startswith("postgres://"):
            return trimmed.replace("postgres://", "postgresql+asyncpg://", 1)
        if trimmed.startswith("postgresql://"):
            return trimmed.replace("postgresql://", "postgresql+asyncpg://", 1)
        return trimmed

    @model_validator(mode="after")
    def apply_development_defaults(self) -> Self:
        if self.env == "development":
            if "FILIGRANE_SESSION_COOKIE_SECURE" not in os.environ:
                self.session_cookie_secure = False
            if "FILIGRANE_OPENAPI_ENABLED" not in os.environ:
                self.openapi_enabled = True
        return self

    def session_cookie_name(self) -> str:
        if self.env == "development":
            return "fg_session"
        return "__Host-fg_session"

    def parsed_cors_origins(self) -> list[str]:
        return _split_csv(self.cors_origins)

    def chrome_extension_origins(self) -> list[str]:
        chrome_ids = _split_csv(self.chrome_extension_ids)
        return [f"chrome-extension://{ext_id}" for ext_id in chrome_ids if ext_id]


def _split_csv(raw: str) -> list[str]:
    items = [part.strip().rstrip("/") for part in raw.split(",")]
    return [item for item in items if item]


@lru_cache
def get_settings() -> FiligraneSettings:
    return FiligraneSettings()
