# services/projects.py

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from models import Project, ConnectionRequest
from repositories import create_project, list_projects, get_project_by_id


async def create_user_project(
    session: AsyncSession,
    *,
    owner_telegram_id: int,
    title: str,
    stack: str | None,
    idea: str,
    status: str | None = None,
    needs_now: str | None = None,
    looking_for_role: str | None = None,
    level: str | None = None,
    extra: str | None = None,
    image_file_id: str | None = None,
    team_limit: int | None = None,
    chat_link: str | None = None,
) -> Project:
    """
    Создание проекта от пользователя.
    """
    # Если статус не передали — ставим дефолтный
    final_status = status or "💡 Идея"

    return await create_project(
        session,
        owner_telegram_id=owner_telegram_id,
        title=title,
        stack=stack,
        idea=idea,
        looking_for_role=looking_for_role,
        level=level,
        extra=extra,
        image_file_id=image_file_id,
        status=final_status,
        needs_now=needs_now,
        team_limit=team_limit,
        chat_link=chat_link,
    )


async def _get_blocked_project_ids_for_user(
    session: AsyncSession,
    requester_id: int,
) -> set[int]:
    """
    Множество id проектов, по которым пользователь уже:
    - отправил заявку (pending),
    - или уже принят (accepted).

    Такие проекты в ленте ему не показываем, чтобы не спамить.
    """
    stmt = select(ConnectionRequest.project_id).where(
        ConnectionRequest.from_telegram_id == requester_id,
        ConnectionRequest.project_id.is_not(None),
        ConnectionRequest.status.in_(["pending", "accepted"]),
    )
    result = await session.execute(stmt)
    rows = result.scalars().all()
    # project_id может быть None, отфильтруем
    return {pid for pid in rows if pid is not None}


async def get_projects_feed(
    session: AsyncSession,
    *,
    limit: int = 20,
    requester_id: int | None = None,
    role: str | None = None,
    stack: str | None = None,
    level: str | None = None,
) -> list[Project]:
    """
    Лента проектов.

    role  — строка, по которой ищем в Project.looking_for_role (LIKE %role%),
    stack — строка, по которой ищем в Project.stack (LIKE %stack%),
    level — точное совпадение Project.level.

    Если requester_id не задан:
      - просто возвращаем последние активные проекты по фильтрам.

    Если requester_id задан:
      - не показываем собственные проекты пользователя,
      - не показываем проекты, на которые он уже отправлял заявку
        или в которых уже принят (по project_id).
    """
    # Без requester_id — просто отдаем отфильтрованный список
    if requester_id is None:
        return await list_projects(
            session,
            limit=limit,
            role=role,
            stack=stack,
            level=level,
        )

    blocked_project_ids = await _get_blocked_project_ids_for_user(session, requester_id)

    # Берём с запасом, потому что часть проектов отфильтруем
    base_projects = await list_projects(
        session,
        limit=limit * 3,
        role=role,
        stack=stack,
        level=level,
    )

    projects: list[Project] = []
    for p in base_projects:
        # свои проекты не показываем
        if p.owner_telegram_id == requester_id:
            continue

        # проекты, на которые уже откликались / уже в команде
        if p.id in blocked_project_ids:
            continue

        projects.append(p)
        if len(projects) >= limit:
            break

    return projects


async def get_project(
    session: AsyncSession,
    project_id: int,
) -> Project | None:
    return await get_project_by_id(session, project_id)
