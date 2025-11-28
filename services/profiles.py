# services/profiles.py
from typing import Sequence

from aiogram.types import User
from sqlalchemy.ext.asyncio import AsyncSession

from models import Profile
from repositories import (
    get_or_create_profile,
    get_profile_by_telegram_id,
    update_profile,
    search_profiles,
)


async def ensure_profile(
    session: AsyncSession,
    tg_user: User,
) -> Profile:
    """
    Убедиться, что у пользователя есть строка профиля в БД.
    Поля имени/аватара заполняются отдельно при регистрации.
    """
    profile = await get_or_create_profile(
        session,
        telegram_id=tg_user.id,
        username=tg_user.username,
    )
    return profile


async def get_profile(
    session: AsyncSession,
    telegram_id: int,
) -> Profile | None:
    return await get_profile_by_telegram_id(session, telegram_id)


async def update_profile_data(
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
    return await update_profile(
        session,
        telegram_id=telegram_id,
        first_name=first_name,
        avatar_file_id=avatar_file_id,
        role=role,
        stack=stack,
        framework=framework,
        skills=skills,
        goals=goals,
        about=about,
    )


async def search_profiles_for_user(
    session: AsyncSession,
    *,
    requester_id: int,
    goal: str | None = None,
    role: str | None = None,
    limit: int = 20,
) -> Sequence[Profile]:
    profiles = await search_profiles(
        session,
        goal=goal,
        role=role,
        exclude_telegram_id=requester_id,
        limit=limit,
    )
    return profiles
