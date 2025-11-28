# middlewares/db.py
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from sqlalchemy.ext.asyncio import AsyncSession

from db import async_session_maker


class DbSessionMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        # Открываем сессию на время обработки апдейта
        async with async_session_maker() as session:  # type: AsyncSession
            # прокидываем сессию в data — aiogram сам пробросит её как аргумент в хендлер
            data["session"] = session
            return await handler(event, data)
