# logging_config.py
from __future__ import annotations

import contextvars
import json
import logging
from logging.config import dictConfig
from typing import Any, Dict

from config import settings

# Контекст для корреляции логов с апдейтом
user_id_var = contextvars.ContextVar("user_id", default="-")
chat_id_var = contextvars.ContextVar("chat_id", default="-")
update_id_var = contextvars.ContextVar("update_id", default="-")


class ContextFormatter(logging.Formatter):
    """Форматер для dev: добавляет user_id / chat_id / update_id из contextvars, если их нет в record."""

    def format(self, record: logging.LogRecord) -> str:  # type: ignore[override]
        if not hasattr(record, "user_id"):
            record.user_id = user_id_var.get()
        if not hasattr(record, "chat_id"):
            record.chat_id = chat_id_var.get()
        if not hasattr(record, "update_id"):
            record.update_id = update_id_var.get()
        return super().format(record)


class JsonFormatter(logging.Formatter):
    """JSON-логгер для проды."""

    def format(self, record: logging.LogRecord) -> str:  # type: ignore[override]
        # подтянем контекст
        user_id = getattr(record, "user_id", user_id_var.get())
        chat_id = getattr(record, "chat_id", chat_id_var.get())
        update_id = getattr(record, "update_id", update_id_var.get())

        log: Dict[str, Any] = {
            "ts": self.formatTime(record, self.datefmt),
            "env": settings.env,
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "user_id": user_id,
            "chat_id": chat_id,
            "update_id": update_id,
            "module": record.module,
            "func": record.funcName,
            "line": record.lineno,
        }

        if record.exc_info:
            log["exc_info"] = self.formatException(record.exc_info)

        return json.dumps(log, ensure_ascii=False)


def build_logging_config() -> dict:
    """Собираем dictConfig для logging."""

    is_prod = settings.env == "prod"
    level = settings.log_level.upper()

    formatter_name = "json" if is_prod else "console"

    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "console": {
                "()": "logging_config.ContextFormatter",
                "format": (
                    "%(asctime)s | %(levelname)-8s | %(name)s | "
                    "u=%(user_id)s c=%(chat_id)s upd=%(update_id)s | %(message)s"
                ),
            },
            "json": {
                "()": "logging_config.JsonFormatter",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": formatter_name,
                "level": level,
            },
            "file": {
                "class": "logging.FileHandler",
                "filename": "bot.log",
                "encoding": "utf-8",
                "formatter": formatter_name,
                "level": level,
            },
        },
        "root": {
            "handlers": ["console", "file"],
            "level": level,
        },
        # Немного приручаем болтливые логгеры сторонних либ
        "loggers": {
            "aiogram": {
                "level": "INFO",
                "handlers": ["console", "file"],
                "propagate": False,
            },
            "sqlalchemy.engine": {
                "level": "WARNING",
                "handlers": ["console", "file"],
                "propagate": False,
            },
        },
    }


_CONFIGURED = False


def setup_logging() -> logging.Logger:
    """Инициализация логирования для всего приложения (идемпотентная)."""
    global _CONFIGURED
    if not _CONFIGURED:
        cfg = build_logging_config()
        dictConfig(cfg)
        _CONFIGURED = True

    logger = logging.getLogger(__name__)
    logger.debug(
        "Logging initialized (env=%s, level=%s)", settings.env, settings.log_level
    )
    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    """
    Удобный хелпер: гарантирует, что логирование настроено,
    и возвращает модульный логгер.
    """
    if not _CONFIGURED:
        setup_logging()
    return logging.getLogger(name or __name__)
