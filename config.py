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
    max_connection_requests_per_day: int
    reminders_after_days: int
    reminders_interval_hours: int


def get_settings() -> Settings:
    return Settings(
        bot_token=os.getenv("BOT_TOKEN", ""),
        database_url=os.getenv(
            "DATABASE_URL",
            "sqlite+aiosqlite:///./linkit.db",
        ),
        # сколько заявок в день можно отправить одному пользователю
        max_connection_requests_per_day=int(
            os.getenv("MAX_CONNECTION_REQUESTS_PER_DAY", "10")
        ),
        # через сколько дней после принятия заявки слать напоминание
        reminders_after_days=int(os.getenv("REMINDERS_AFTER_DAYS", "3")),
        # как часто проверять напоминания (в часах)
        reminders_interval_hours=int(os.getenv("REMINDERS_INTERVAL_HOURS", "6")),
    )


settings = get_settings()
