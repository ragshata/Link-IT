# handlers/errors.py
from __future__ import annotations

import logging
from typing import Optional

from aiogram import Dispatcher, Bot
from aiogram.types import ErrorEvent, Update

from config import settings

logger = logging.getLogger(__name__)


def _extract_user_chat_from_update(
    update: Update,
) -> tuple[Optional[int], Optional[int]]:
    user_id = None
    chat_id = None

    try:
        if update.message:
            if update.message.from_user:
                user_id = update.message.from_user.id
            if update.message.chat:
                chat_id = update.message.chat.id
        elif update.callback_query:
            cq = update.callback_query
            if cq.from_user:
                user_id = cq.from_user.id
            if cq.message and cq.message.chat:
                chat_id = cq.message.chat.id
        elif update.inline_query:
            if update.inline_query.from_user:
                user_id = update.inline_query.from_user.id
    except Exception:
        logger.debug(
            "Failed to extract user/chat from Update in error handler", exc_info=True
        )

    return user_id, chat_id


def setup_error_handlers(dp: Dispatcher, bot: Bot) -> None:
    @dp.errors()
    async def error_handler(event: ErrorEvent, exception: Exception) -> None:
        # Логируем стек
        logger.exception("Unhandled error while processing update")

        if not settings.admin_chat_id:
            return

        user_id = None
        chat_id = None
        try:
            if event.update:
                user_id, chat_id = _extract_user_chat_from_update(event.update)
        except Exception:
            logger.debug("Failed to extract update from ErrorEvent", exc_info=True)

        # Собираем короткое уведомление для админа
        text_lines = ["🔥 Ошибка в боте."]
        if user_id:
            text_lines.append(f"Пользователь: {user_id}")
        if chat_id:
            text_lines.append(f"Чат: {chat_id}")
        text_lines.append(f"Исключение: {type(exception).__name__}")

        text = "\n".join(text_lines)

        try:
            await bot.send_message(chat_id=settings.admin_chat_id, text=text)
        except Exception:
            logger.debug("Failed to send error notification to admin", exc_info=True)
