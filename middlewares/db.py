# middlewares/db.py
from typing import Any, Awaitable, Callable, Dict
import logging

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from db import async_session_maker

logger = logging.getLogger(__name__)


class DbSessionMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        """
        Открываем сессию БД и оборачиваем обработку апдейта try/except.

        Любая необработанная ошибка внутри хендлеров:
        - логируется в logger.exception(...)
        - НЕ роняет весь бот
        - по возможности отправляет пользователю простое сообщение об ошибке
        """
        async with async_session_maker() as session:  # type: AsyncSession
            data["session"] = session
            try:
                return await handler(event, data)
            except Exception:
                logger.exception("Unhandled error while processing update: %r", event)

                # Попробуем аккуратно уведомить пользователя (если это Message/CallbackQuery)
                try:
                    if isinstance(event, CallbackQuery):
                        await event.answer(
                            "Что-то пошло не так, мы уже чиним 🛠",
                            show_alert=True,
                        )
                    elif isinstance(event, Message):
                        await event.answer(
                            "Упс, случилась ошибка. Попробуй ещё раз чуть позже."
                        )
                except Exception:
                    # Даже если не получилось отправить сообщение — просто молча проглатываем
                    logger.exception("Failed to send error notification to user")

                # Ничего не возвращаем — aiogram спокойно продолжит работать
                return None
