# init_db.py
import asyncio

from db import engine


async def init_db() -> None:
    """
    Проверка подключения к базе.

    ВАЖНО:
    - Схема БД теперь создаётся и изменяется ТОЛЬКО через Alembic миграции.
    - Здесь мы просто убеждаемся, что можем открыть соединение.
    """
    async with engine.begin() as conn:
        # Ничего не делаем — если подключение успешно, значит всё ок.
        pass


if __name__ == "__main__":
    # Можно выполнить как:
    #   python -m init_db
    asyncio.run(init_db())
