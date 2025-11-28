# init_db.py
import asyncio

from db import engine, Base
import models  # noqa: F401  # важно, чтобы модели были импортированы


async def init_db() -> None:
    # Создаём все таблицы, которые описаны в models.* (через Base.metadata)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


if __name__ == "__main__":
    # Можно выполнить как:
    #   python -m init_db
    asyncio.run(init_db())
