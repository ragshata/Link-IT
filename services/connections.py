# services/connections.py
from sqlalchemy.ext.asyncio import AsyncSession

from models import ConnectionRequest
from repositories import (
    get_pending_request_between,
    create_connection_request,
    get_connection_request_by_id,
    set_connection_request_status,
)
from datetime import datetime, timezone
from sqlalchemy import select


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
    """
    if from_id == to_id:
        return None, "self"

    existing = await get_pending_request_between(
        session,
        from_id=from_id,
        to_id=to_id,
    )
    if existing:
        return existing, "exists"

    req = await create_connection_request(
        session,
        from_id=from_id,
        to_id=to_id,
    )
    return req, "ok"


async def accept_connection_request(
    session: AsyncSession,
    *,
    request_id: int,
) -> ConnectionRequest | None:
    q = select(ConnectionRequest).where(ConnectionRequest.id == request_id)
    req = (await session.execute(q)).scalar_one_or_none()
    if not req:
        return None

    req.status = "accepted"
    req.accepted_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(req)
    return req


async def reject_connection_request(
    session: AsyncSession,
    *,
    request_id: int,
) -> ConnectionRequest | None:
    return await set_connection_request_status(
        session,
        request_id=request_id,
        status="rejected",
    )


async def get_connection_request(
    session: AsyncSession,
    *,
    request_id: int,
) -> ConnectionRequest | None:
    return await get_connection_request_by_id(session, request_id)
