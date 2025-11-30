# services/profiles.py
from typing import Sequence

from aiogram.types import User
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from models import Profile, ConnectionRequest
from repositories import (
    get_or_create_profile,
    get_profile_by_telegram_id,
    update_profile as repo_update_profile,
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
    *,
    profile: Profile | None = None,
    telegram_id: int | None = None,
    first_name: str | None = None,
    avatar_file_id: str | None = None,
    role: str | None = None,
    stack: str | None = None,
    framework: str | None = None,
    skills: str | None = None,
    goals: str | None = None,
    about: str | None = None,
) -> Profile | None:
    """
    Обновление профиля через сервисный слой.

    Можно передать:
    - либо profile=Profile,
    - либо telegram_id=... (если профиля на руках нет).

    В репозиторий уходит только telegram_id + поля для обновления.
    """
    if profile is not None:
        telegram_id = profile.telegram_id

    if telegram_id is None:
        raise ValueError("Нужно передать либо profile, либо telegram_id")

    updated_profile = await repo_update_profile(
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
    return updated_profile


# ===== хелперы для фильтрации =====


def _is_profile_empty(profile: Profile) -> bool:
    """
    Профиль считаем пустым, если все ключевые поля не заполнены.
    Такие профили не показываем в ленте.
    """
    fields = [
        profile.first_name,
        profile.role,
        profile.stack,
        profile.framework,
        profile.skills,
        profile.goals,
        profile.about,
    ]
    return not any((value is not None) and str(value).strip() for value in fields)


async def _get_requested_ids_for_user(
    session: AsyncSession,
    requester_id: int,
) -> set[int]:
    """
    Возвращаем множество telegram_id тех, кому юзер уже отправлял заявки
    (любого статуса: pending / accepted / rejected).
    """
    stmt = select(ConnectionRequest.to_telegram_id).where(
        ConnectionRequest.from_telegram_id == requester_id,
    )
    result = await session.execute(stmt)
    rows = result.fetchall()
    return {row[0] for row in rows}


# ===== поиск профилей для ленты =====


async def search_profiles_for_user(
    session: AsyncSession,
    *,
    requester_id: int,
    goal: str | None = None,
    role: str | None = None,
    limit: int = 20,
) -> Sequence[Profile]:
    """
    Профили для ленты:
    - без самого пользователя
    - без пустых профилей
    - без тех, кому пользователь уже отправлял заявку
    """
    # 1) Узнаём, кому уже отправлялись заявки
    requested_ids = await _get_requested_ids_for_user(session, requester_id)

    # 2) Берём базовый список по goal/role (без самого себя)
    # Берём с запасом (x3), чтобы после фильтрации всё равно набрать limit
    raw_profiles = await search_profiles(
        session,
        goal=goal,
        role=role,
        exclude_telegram_id=requester_id,
        limit=limit * 3,
    )

    # 3) Фильтруем:
    #    - не пустые
    #    - не те, кому уже отправляли заявки
    profiles: list[Profile] = []
    for p in raw_profiles:
        if p.telegram_id in requested_ids:
            continue
        if _is_profile_empty(p):
            continue

        profiles.append(p)
        if len(profiles) >= limit:
            break

    return profiles
