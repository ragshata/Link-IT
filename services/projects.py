# services/projects.py

from sqlalchemy.ext.asyncio import AsyncSession

from models import Project
from repositories import create_project, list_projects, get_project_by_id


async def create_user_project(
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
) -> Project:
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
    )


async def get_projects_feed(
    session: AsyncSession,
    *,
    limit: int = 20,
) -> list[Project]:
    return await list_projects(session, limit=limit)


async def get_project(
    session: AsyncSession,
    project_id: int,
) -> Project | None:
    return await get_project_by_id(session, project_id)
