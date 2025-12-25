# services/connections.py
import logging
from datetime import datetime

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models import ConnectionRequest
from repositories import (
    get_pending_request_between,
    create_connection_request,
    get_connection_request_by_id,
    set_connection_request_status,
    count_connection_requests_from_user_today,
)

logger = logging.getLogger(__name__)

# Лимит заявок в день на одного пользователя
MAX_CONNECTION_REQUESTS_PER_DAY = settings.max_connection_requests_per_day


async def send_connection_request(
    session: AsyncSession,
    *,
    from_id: int,
    to_id: int,
) -> tuple[ConnectionRequest | None, str]:
    """
    Возвращаем (request, reason)
    reason:
      - "ok" — новая заявка
      - "self" — попытка отправить себе
      - "exists" — уже есть pending
      - "limit" — достигнут дневной лимит
    """
    if from_id == to_id:
        return None, "self"

    # Если заявка уже есть — это не “новая попытка”, лимит не тратим
    existing = await get_pending_request_between(
        session,
        from_id=from_id,
        to_id=to_id,
    )
    if existing:
        return existing, "exists"

    # ===== лимит на день =====
    start_of_day = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    q = select(func.count(ConnectionRequest.id)).where(
        ConnectionRequest.from_telegram_id == from_id,
        ConnectionRequest.created_at >= start_of_day,
    )
    sent_today = (await session.execute(q)).scalar_one() or 0

    if sent_today >= settings.max_connection_requests_per_day:
        return None, "limit"
    # =========================

    req = await create_connection_request(
        session,
        from_id=from_id,
        to_id=to_id,
    )
    return req, "ok"


async def reject_connection_request(
    session: AsyncSession,
    *,
    request_id: int,
) -> ConnectionRequest | None:
    req = await set_connection_request_status(
        session,
        request_id=request_id,
        status="rejected",
    )
    if not req:
        logger.info(
            "connection_request_reject_not_found request_id=%s",
            request_id,
        )
        return None

    logger.info(
        "connection_request_rejected request_id=%s from_id=%s to_id=%s status=%s",
        req.id,
        req.from_telegram_id,
        req.to_telegram_id,
        req.status,
    )

    return req


async def get_connection_request(
    session: AsyncSession,
    *,
    request_id: int,
) -> ConnectionRequest | None:
    req = await get_connection_request_by_id(session, request_id)
    logger.info(
        "connection_request_fetched request_id=%s found=%s",
        request_id,
        bool(req),
    )
    return req
