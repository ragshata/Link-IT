# config.py
from __future__ import annotations

from functools import lru_cache
from typing import Literal, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Telegram bot
    bot_token: str = Field(alias="BOT_TOKEN")

    # Database
    database_url: str = Field(
        default="sqlite+aiosqlite:///./linkit.db",
        alias="DATABASE_URL",
    )

    # Environment
    env: Literal["dev", "stage", "prod"] = Field("dev", alias="ENV")
    log_level: str = Field("INFO", alias="LOG_LEVEL")

    # Limits & reminders
    max_connection_requests_per_day: int = Field(
        10,
        alias="MAX_CONNECTION_REQUESTS_PER_DAY",
    )
    reminders_after_days: int = Field(
        3,
        alias="REMINDERS_AFTER_DAYS",
    )
    reminders_interval_hours: int = Field(
        6,
        alias="REMINDERS_INTERVAL_HOURS",
    )

    # Admin / alerts
    admin_chat_id: Optional[int] = Field(
        default=None,
        alias="ADMIN_CHAT_ID",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    @field_validator("reminders_after_days", mode="before")
    @classmethod
    def parse_reminders_after_days(cls, v):
        """
        Поддержка формата:
        - просто число: "3"
        - несколько чисел через запятую: "2,7" -> берём первое (2)
        """
        if isinstance(v, str):
            first = v.split(",")[0].strip()
            return int(first)
        return int(v)


@lru_cache
def get_settings() -> Settings:
    # кэшируем, чтобы не читать .env каждый раз
    return Settings()


settings = get_settings()
