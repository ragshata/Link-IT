# config.py
import os
from dataclasses import dataclass

from dotenv import load_dotenv


# грузим переменные из .env файла в окружение
load_dotenv()


@dataclass
class Settings:
    bot_token: str
    database_url: str


def get_settings() -> Settings:
    return Settings(
        bot_token=os.getenv("BOT_TOKEN", ""),
        database_url=os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./linkit.db"),
    )


settings = get_settings()
