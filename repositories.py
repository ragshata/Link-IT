from datetime import datetime, timedelta

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from models import Profile, ConnectionRequest, Project


# ---------- профили ----------


async def ensure_profile_exists(
    session: AsyncSession,
    telegram_id: int,
    username: str | None = None,
) -> Profile:
    profile = await session.scalar(
        select(Profile).where(Profile.telegram_id == telegram_id)
    )
    if profile:
        if username and profile.username != username:
            profile.username = username
            await session.commit()
            await session.refresh(profile)
        return profile

    new_profile = Profile(
        telegram_id=telegram_id,
        username=username,
    )
    session.add(new_profile)
    await session.commit()
    await session.refresh(new_profile)
    return new_profile


async def get_profile_by_telegram_id(
    session: AsyncSession, telegram_id: int
) -> Profile | None:
    return await session.scalar(
        select(Profile).where(Profile.telegram_id == telegram_id)
    )


async def update_profile(
    session: AsyncSession,
    telegram_id: int,
    *,
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


async def search_profiles(
    session: AsyncSession, *, exclude_id: int | None = None
) -> list[Profile]:
    query = select(Profile)
    if exclude_id is not None:
        query = query.where(Profile.telegram_id != exclude_id)
    result = await session.scalars(query.order_by(Profile.id.desc()))
    return list(result)


# ---------- проекты ----------


async def create_project(
    session: AsyncSession,
    *,
    owner_telegram_id: int,
    title: str | None,
    stack: str | None,
    idea: str | None,
    looking_for_role: str | None,
    level: str | None,
    extra: str | None,
    image_file_id: str | None,
    status: str,
    needs_now: str | None,
    team_limit: int | None = None,
    chat_link: str | None = None,
) -> Project:
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
        current_members=1,
    )
    session.add(project)
    await session.commit()
    await session.refresh(project)
    return project


async def get_project_by_id(session: AsyncSession, project_id: int) -> Project | None:
    return await session.scalar(select(Project).where(Project.id == project_id))


async def get_projects(
    session: AsyncSession, *, exclude_owner_id: int | None = None
) -> list[Project]:
    query = select(Project)
    if exclude_owner_id is not None:
        query = query.where(Project.owner_telegram_id != exclude_owner_id)
    result = await session.scalars(query.order_by(Project.id.desc()))
    return list(result)


# ---------- заявки на коннекты / проект ----------


async def create_connection_request(
    session: AsyncSession,
    *,
    from_id: int,
    to_id: int,
    project_id: int | None = None,
) -> ConnectionRequest:
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


async def get_pending_request_between(
    session: AsyncSession,
    *,
    from_id: int,
    to_id: int,
) -> ConnectionRequest | None:
    query = select(ConnectionRequest).where(
        ConnectionRequest.from_telegram_id == from_id,
        ConnectionRequest.to_telegram_id == to_id,
        ConnectionRequest.status == "pending",
    )
    return await session.scalar(query)


async def get_pending_connect_request_between(
    session: AsyncSession,
    *,
    from_id: int,
    to_id: int,
) -> ConnectionRequest | None:
    """Pending обычная заявка на коннект (project_id IS NULL)."""
    query = select(ConnectionRequest).where(
        ConnectionRequest.from_telegram_id == from_id,
        ConnectionRequest.to_telegram_id == to_id,
        ConnectionRequest.status == "pending",
        ConnectionRequest.project_id.is_(None),
    )
    return await session.scalar(query)


async def get_pending_project_request_between(
    session: AsyncSession,
    *,
    from_id: int,
    to_id: int,
    project_id: int,
) -> ConnectionRequest | None:
    """Pending проектная заявка (строго по project_id)."""
    query = select(ConnectionRequest).where(
        ConnectionRequest.from_telegram_id == from_id,
        ConnectionRequest.to_telegram_id == to_id,
        ConnectionRequest.status == "pending",
        ConnectionRequest.project_id == project_id,
    )
    return await session.scalar(query)


async def count_connection_requests_from_user_today(
    session: AsyncSession,
    *,
    from_id: int,
) -> int:
    now = datetime.utcnow()
    start_of_day = datetime(now.year, now.month, now.day)
    end_of_day = start_of_day + timedelta(days=1)

    query = select(func.count(ConnectionRequest.id)).where(
        ConnectionRequest.from_telegram_id == from_id,
        ConnectionRequest.created_at >= start_of_day,
        ConnectionRequest.created_at < end_of_day,
    )
    return int(await session.scalar(query) or 0)


async def get_connection_request_by_id(
    session: AsyncSession,
    request_id: int,
) -> ConnectionRequest | None:
    return await session.scalar(
        select(ConnectionRequest).where(ConnectionRequest.id == request_id)
    )


async def set_connection_request_status(
    session: AsyncSession,
    *,
    request_id: int,
    status: str,
) -> ConnectionRequest | None:
    req = await get_connection_request_by_id(session, request_id)
    if not req:
        return None

    req.status = status
    req.responded_at = datetime.utcnow()

    await session.commit()
    await session.refresh(req)
    return req
