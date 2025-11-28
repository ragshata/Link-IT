import asyncio

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
    devfeed_router,
)
from middlewares.db import DbSessionMiddleware


async def main() -> None:
    if not settings.bot_token:
        raise RuntimeError("BOT_TOKEN не задан в переменных окружения")

    # 1. Инициализируем БД
    await init_db()

    # 2. Бот и диспетчер
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    # 3. Middleware для БД — на все апдейты
    dp.update.middleware(DbSessionMiddleware())

    # 4. Роутеры
    dp.include_router(start_router)
    dp.include_router(profile_router)
    dp.include_router(browse_router)
    dp.include_router(projects_router)
    dp.include_router(devfeed_router)

    # 5. Старт
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
