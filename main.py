# main.py
import asyncio
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
    connection_requests_router,
    devfeed_filters_router,
    devfeed_router,
)

from handlers.errors import setup_error_handlers
from logging_config import setup_logging
from middlewares.db import DbSessionMiddleware
from middlewares.logging_context import LoggingContextMiddleware
from services.reminders import reminders_worker


async def main() -> None:
    # 1. Логирование
    logger = setup_logging()
    logger.info("Starting LinkIT bot in %s environment", settings.env)

    # 2. Инициализация БД (если тут всё упало — логируем и выходим)
    try:
        await init_db()
    except Exception:
        logger.exception("Database initialization failed")
        return

    logger.info("Database is initialized")

    # 3. Бот и диспетчер
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    # 3.1. Middleware
    # Сначала — контекст логов (user/chat/update),
    # потом — сессия БД (чтобы в логах уже были user_id/chat_id).
    dp.update.outer_middleware(LoggingContextMiddleware())
    dp.update.outer_middleware(DbSessionMiddleware())

    # 4. Роутеры
    dp.include_router(start_router)
    dp.include_router(profile_router)
    dp.include_router(browse_router)
    dp.include_router(projects_router)
    dp.include_router(connection_requests_router)
    dp.include_router(devfeed_filters_router)  # сначала фильтры
    dp.include_router(devfeed_router)  # потом сама лента

    logger.info("Routers and middlewares are configured")

    # 5. Error-handlers (глобальный ловец исключений в апдейтах)
    setup_error_handlers(dp, bot)
    logger.info("Error handlers are set up")

    # 6. Фоновый воркер напоминаний
    reminders_task = asyncio.create_task(
        reminders_worker(bot),
        name="reminders_worker",
    )
    logger.info("Reminders worker started")

    # 7. Стартуем поллинг
    try:
        logger.info("Starting polling")
        await dp.start_polling(bot)
    except asyncio.CancelledError:
        # Нормальное завершение (Ctrl+C и т.п.)
        logger.info("Bot polling cancelled, shutting down...")
    except Exception:
        logger.exception("Bot stopped by unexpected error")
    finally:
        # Аккуратно гасим воркер напоминаний
        reminders_task.cancel()
        with suppress(asyncio.CancelledError):
            await reminders_task

        # Закрываем HTTP-сессию бота
        with suppress(Exception):
            await bot.session.close()

        logger.info("Bot shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
