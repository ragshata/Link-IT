# middlewares/logging_context.py
from __future__ import annotations

import logging
from typing import Any, Callable, Awaitable, Dict

from aiogram import BaseMiddleware
from aiogram.types import Update

from logging_config import user_id_var, chat_id_var, update_id_var

logger = logging.getLogger(__name__)


class LoggingContextMiddleware(BaseMiddleware):
    """
    Заполняет contextvars.user_id/chat_id/update_id для всех логов,
    которые происходят во время обработки одного апдейта.
    """

    async def __call__(
        self,
        handler: Callable[[Update, Dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: Dict[str, Any],
    ) -> Any:
        user_id = "-"
        chat_id = "-"
        update_id = "-"

        if isinstance(event, Update):
            update_id = str(event.update_id)

            try:
                if event.message:
                    if event.message.from_user:
                        user_id = str(event.message.from_user.id)
                    if event.message.chat:
                        chat_id = str(event.message.chat.id)
                elif event.callback_query:
                    cq = event.callback_query
                    if cq.from_user:
                        user_id = str(cq.from_user.id)
                    if cq.message and cq.message.chat:
                        chat_id = str(cq.message.chat.id)
                elif event.inline_query:
                    if event.inline_query.from_user:
                        user_id = str(event.inline_query.from_user.id)
                # при желании можно добить другие типы апдейтов
            except Exception:
                logger.debug("Failed to extract user/chat from Update", exc_info=True)

        token_user = user_id_var.set(user_id)
        token_chat = chat_id_var.set(chat_id)
        token_update = update_id_var.set(update_id)

        try:
            return await handler(event, data)
        finally:
            # возвращаем старые значения, чтобы не течь между апдейтами
            user_id_var.reset(token_user)
            chat_id_var.reset(token_chat)
            update_id_var.reset(token_update)
