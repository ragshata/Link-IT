# main.py
import asyncio
import logging
from contextlib import suppress

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

from config import settings
from init_db import init_db
from handlers import (
    start_router,
    profile_router,
    browse_router,
    projects_router,
    requests_router,
    devfeed_filters_router,
    devfeed_router,
)
from middlewares.db import DbSessionMiddleware
from services.reminders import reminders_worker


async def main() -> None:
    # 1. Логирование
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        handlers=[
            logging.StreamHandler(),  # в консоль
            logging.FileHandler("bot.log", encoding="utf-8"),  # в файл bot.log
        ],
    )
    logger = logging.getLogger(__name__)
    logger.info("Starting LinkIT bot...")

    # 2. Инициализация БД
    await init_db()
    logger.info("Database is initialized")

    # 3. Бот и диспетчер
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    # 3.1. Middleware с сессией БД + глобальный try/except на апдейт
    dp.update.outer_middleware(DbSessionMiddleware())

    # 4. Роутеры
    dp.include_router(start_router)
    dp.include_router(profile_router)
    dp.include_router(browse_router)
    dp.include_router(projects_router)
    dp.include_router(requests_router)
    dp.include_router(devfeed_filters_router)  # сначала фильтры
    dp.include_router(devfeed_router)  # потом сама лента

    # 5. Фоновый воркер напоминаний
    reminders_task = asyncio.create_task(reminders_worker(bot))

    # 6. Стартуем поллинг
    try:
        await dp.start_polling(bot)
    except Exception:
        logger.exception("Bot stopped by unexpected error")
    finally:
        # Аккуратно гасим воркер напоминаний
        reminders_task.cancel()
        with suppress(asyncio.CancelledError):
            await reminders_task


if __name__ == "__main__":
    asyncio.run(main())
