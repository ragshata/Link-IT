# services/connections.py
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models import ConnectionRequest
from repositories import (
    get_pending_connect_request_between,
    get_pending_project_request_between,
    create_connection_request,
    get_connection_request_by_id,
    set_connection_request_status,
    count_connection_requests_from_user_today,
)

logger = logging.getLogger(__name__)


async def send_connect_request(
    session: AsyncSession,
    *,
    from_id: int,
    to_id: int,
) -> tuple[ConnectionRequest | None, str]:
    """
    Обычная заявка на коннект (НЕ проектная).

    Возвращаем (request, reason)
    reason:
      - "ok" — новая заявка
      - "self" — попытка отправить себе
      - "exists" — уже есть pending (только connect, project_id IS NULL)
      - "limit" — достигнут дневной лимит
    """
    if from_id == to_id:
        return None, "self"

    existing = await get_pending_connect_request_between(
        session,
        from_id=from_id,
        to_id=to_id,
    )
    if existing:
        return existing, "exists"

    sent_today = await count_connection_requests_from_user_today(
        session, from_id=from_id
    )
    if sent_today >= settings.max_connection_requests_per_day:
        return None, "limit"

    req = await create_connection_request(
        session,
        from_id=from_id,
        to_id=to_id,
        project_id=None,
    )
    return req, "ok"


async def send_project_request(
    session: AsyncSession,
    *,
    from_id: int,
    to_id: int,
    project_id: int,
) -> tuple[ConnectionRequest | None, str]:
    """
    Проектная заявка (строго с project_id).

    Возвращаем (request, reason)
    reason:
      - "ok" — новая заявка
      - "self" — попытка отправить себе
      - "exists" — уже есть pending по этому же project_id
      - "limit" — достигнут дневной лимит
    """
    if from_id == to_id:
        return None, "self"

    existing = await get_pending_project_request_between(
        session,
        from_id=from_id,
        to_id=to_id,
        project_id=project_id,
    )
    if existing:
        return existing, "exists"

    sent_today = await count_connection_requests_from_user_today(
        session, from_id=from_id
    )
    if sent_today >= settings.max_connection_requests_per_day:
        return None, "limit"

    req = await create_connection_request(
        session,
        from_id=from_id,
        to_id=to_id,
        project_id=project_id,
    )
    return req, "ok"


# Backward-compat: старое имя (если где-то осталось).
async def send_connection_request(
    session: AsyncSession,
    *,
    from_id: int,
    to_id: int,
) -> tuple[ConnectionRequest | None, str]:
    return await send_connect_request(session, from_id=from_id, to_id=to_id)


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
