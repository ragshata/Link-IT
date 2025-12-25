from typing import Sequence

from sqlalchemy import select, desc, func
from sqlalchemy.ext.asyncio import AsyncSession

from models import Profile, Project, ConnectionRequest


# ===== ПРОФИЛИ =====


async def get_profile_by_telegram_id(
    session: AsyncSession,
    telegram_id: int,
) -> Profile | None:
    stmt = select(Profile).where(Profile.telegram_id == telegram_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def update_profile(
    session: AsyncSession,
    *,
    telegram_id: int,
    first_name: str | None = None,
    avatar_file_id: str | None = None,
    role: str | None = None,
    stack: str | None = None,
    framework: str | None = None,
    skills: str | None = None,
    goals: str | None = None,
    about: str | None = None,
) -> Profile | None:
    profile = await get_profile_by_telegram_id(session, telegram_id)
    if not profile:
        return None

    if first_name is not None:
        profile.first_name = first_name
    if avatar_file_id is not None:
        profile.avatar_file_id = avatar_file_id
    if role is not None:
        profile.role = role
    if stack is not None:
        profile.stack = stack
    if framework is not None:
        profile.framework = framework
    if skills is not None:
        profile.skills = skills
    if goals is not None:
        profile.goals = goals
    if about is not None:
        profile.about = about

    await session.commit()
    await session.refresh(profile)
    return profile


async def create_profile(
    session: AsyncSession,
    *,
    telegram_id: int,
    username: str | None,
) -> Profile:
    profile = Profile(
        telegram_id=telegram_id,
        username=username,
    )
    session.add(profile)
    await session.commit()
    await session.refresh(profile)
    return profile


async def get_or_create_profile(
    session: AsyncSession,
    *,
    telegram_id: int,
    username: str | None,
) -> Profile:
    profile = await get_profile_by_telegram_id(session, telegram_id)
    if profile:
        return profile

    return await create_profile(
        session,
        telegram_id=telegram_id,
        username=username,
    )


async def search_profiles(
    session: AsyncSession,
    *,
    goal: str | None = None,
    role: str | None = None,
    exclude_telegram_id: int | None = None,
    limit: int = 20,
) -> Sequence[Profile]:
    stmt = select(Profile).where(Profile.is_active.is_(True))

    if goal:
        like_expr = f"%{goal.lower()}%"
        stmt = stmt.where(Profile.goals.ilike(like_expr))

    if role:
        stmt = stmt.where(Profile.role.ilike(role.lower()))

    if exclude_telegram_id:
        stmt = stmt.where(Profile.telegram_id != exclude_telegram_id)

    stmt = stmt.limit(limit)

    result = await session.execute(stmt)
    return result.scalars().all()


# ===== ПРОЕКТЫ =====


async def create_project(
    session: AsyncSession,
    *,
    owner_telegram_id: int,
    title: str,
    stack: str | None,
    idea: str,
    looking_for_role: str | None = None,
    level: str | None = None,
    extra: str | None = None,
    image_file_id: str | None = None,
    status: str | None = None,
    needs_now: str | None = None,
    team_limit: int | None = None,
    chat_link: str | None = None,
) -> Project:
    """
    Репозиторий для создания проекта.

    status:
      - если передали — сохраняем как есть (например: "idea", "prototype", "frozen").
      - если None — подставляем дефолт "idea".
    """
    if status is None:
        status = "idea"

    project = Project(
        owner_telegram_id=owner_telegram_id,
        title=title,
        stack=stack,
        idea=idea,
        looking_for_role=looking_for_role,
        level=level,
        extra=extra,
        image_file_id=image_file_id,
        status=status,
        needs_now=needs_now,
        team_limit=team_limit,
        chat_link=chat_link,
    )
    session.add(project)
    await session.commit()
    await session.refresh(project)
    return project


async def list_projects(
    session: AsyncSession,
    *,
    limit: int = 20,
    role: str | None = None,
    stack: str | None = None,
    level: str | None = None,
) -> list[Project]:
    """
    Базовый список проектов из БД с простыми фильтрами.
    В сервисном слое (services/projects.py) мы сверху ещё можем
    дополнительно фильтровать по заявкам/владельцу и т.п.
    """
    stmt = select(Project).where(Project.is_active.is_(True))

    if role:
        stmt = stmt.where(Project.looking_for_role.ilike(f"%{role}%"))

    if stack:
        stmt = stmt.where(Project.stack.ilike(f"%{stack}%"))

    if level:
        stmt = stmt.where(Project.level == level)

    stmt = stmt.order_by(desc(Project.created_at)).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_project_by_id(
    session: AsyncSession,
    project_id: int,
) -> Project | None:
    stmt = select(Project).where(
        Project.id == project_id,
        Project.is_active.is_(True),
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


# ===== ЗАЯВКИ НА КОННЕКТ / ПРОЕКТ =====


async def get_connection_request_by_id(
    session: AsyncSession,
    request_id: int,
) -> ConnectionRequest | None:
    stmt = select(ConnectionRequest).where(ConnectionRequest.id == request_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_pending_request_between(
    session: AsyncSession,
    *,
    from_id: int,
    to_id: int,
) -> ConnectionRequest | None:
    """
    Старая логика "чел -> чел": есть ли уже висящая заявка?
    Для заявок на проект мы смотрим по project_id отдельно в сервисах.
    """
    stmt = select(ConnectionRequest).where(
        ConnectionRequest.from_telegram_id == from_id,
        ConnectionRequest.to_telegram_id == to_id,
        ConnectionRequest.status == "pending",
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def count_connection_requests_from_user_today(
    session: AsyncSession,
    *,
    from_id: int,
) -> int:
    """Сколько заявок пользователь отправил за текущие сутки (UTC)."""
    from datetime import datetime as _dt

    now = _dt.utcnow()
    day_start = _dt(year=now.year, month=now.month, day=now.day)

    stmt = select(func.count(ConnectionRequest.id)).where(
        ConnectionRequest.from_telegram_id == from_id,
        ConnectionRequest.created_at >= day_start,
    )
    result = await session.execute(stmt)
    return result.scalar_one()


async def create_connection_request(
    session: AsyncSession,
    *,
    from_id: int,
    to_id: int,
    project_id: int | None = None,
) -> ConnectionRequest:
    """
    Создание заявки:
    - для матчей "разраб → разраб" project_id = None
    - для отклика на проект "разраб → владелец проекта" project_id = id проекта
    """
    req = ConnectionRequest(
        from_telegram_id=from_id,
        to_telegram_id=to_id,
        project_id=project_id,
        status="pending",
    )
    session.add(req)
    await session.commit()
    await session.refresh(req)
    return req


async def set_connection_request_status(
    session: AsyncSession,
    *,
    request_id: int,
    status: str,
) -> ConnectionRequest | None:
    req = await get_connection_request_by_id(session, request_id)
    if not req:
        return None

    from datetime import datetime as _dt

    req.status = status
    req.responded_at = _dt.utcnow()
    await session.commit()
    await session.refresh(req)
    return req
