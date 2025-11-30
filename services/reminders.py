# services/reminders.py

import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from aiogram import Bot

from db import async_session_maker
from models import ConnectionRequest

logger = logging.getLogger(__name__)

# ===== настройки лимитов и напоминаний =====

# Сколько заявок в день один пользователь может отправить
MAX_CONNECTION_REQUESTS_PER_DAY = 10

# Через сколько дней после принятия заявки напоминать
REMINDERS_AFTER_DAYS = 1

# Как часто запускать проверку и окно для попадания в напоминание (в часах)
REMINDERS_INTERVAL_HOURS = 6


# ===== рабочий цикл напоминаний =====


async def reminders_worker(bot: Bot) -> None:
    """
    Фоновая задача:
    раз в REMINDERS_INTERVAL_HOURS часов проверяет принятые заявки
    и рассылает мягкие напоминания.
    """
    logger.info("Reminders worker started")

    while True:
        try:
            async with async_session_maker() as session:
                await _process_reminders(bot, session)
        except asyncio.CancelledError:
            logger.info("Reminders worker cancelled")
            break
        except Exception:
            logger.exception("Error in reminders worker loop")

        await asyncio.sleep(REMINDERS_INTERVAL_HOURS * 3600)


async def _process_reminders(bot: Bot, session: AsyncSession) -> None:
    """
    Ищем заявки со статусом accepted, у которых responded_at в окне:
    [now - REMINDERS_AFTER_DAYS - REMINDERS_INTERVAL_HOURS, now - REMINDERS_AFTER_DAYS]

    Так каждая принятая заявка попадёт в окно максимум один раз.
    """
    now = datetime.utcnow()

    cutoff = now - timedelta(days=REMINDERS_AFTER_DAYS)
    window_start = cutoff - timedelta(hours=REMINDERS_INTERVAL_HOURS)

    stmt = select(ConnectionRequest).where(
        and_(
            ConnectionRequest.status == "accepted",
            ConnectionRequest.responded_at.is_not(None),
            ConnectionRequest.responded_at >= window_start,
            ConnectionRequest.responded_at <= cutoff,
        )
    )

    result = await session.execute(stmt)
    requests = list(result.scalars().all())

    if not requests:
        logger.debug("No connection requests for reminders")
        return

    logger.info("Found %d accepted requests for reminders", len(requests))

    text = (
        "Напоминание о контакте в Link IT.\n\n"
        "У тебя есть принятая заявка на общение, но, кажется, давно не было активности.\n"
        "Если тема ещё актуальна — можешь написать собеседнику 🙂"
    )

    for req in requests:
        for chat_id in {req.from_telegram_id, req.to_telegram_id}:
            try:
                await bot.send_message(chat_id=chat_id, text=text)
            except Exception:
                # Не удалось написать (заблокировал бота и т.п.) — просто логируем и идём дальше
                logger.debug(
                    "Failed to send reminder to %s for request %s",
                    chat_id,
                    req.id,
                )
