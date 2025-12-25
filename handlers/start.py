# handlers/start.py

import logging

from aiogram import Router, F, Bot
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from services import ensure_profile, get_profile
from .profile import (
    cmd_profile,
    start_profile_registration,
)  # <-- используем регистрацию БЕЗ отмены
from .projects import start_project_registration  # запуск мастера проекта

router = Router()
logger = logging.getLogger(__name__)


def build_main_menu_keyboard() -> ReplyKeyboardBuilder:
    kb = ReplyKeyboardBuilder()
    kb.button(text="👥 Лента разработчиков")
    kb.button(text="🚀 Лента проектов")
    kb.button(text="🆕 Новый проект")
    kb.button(text="👤 Профиль")
    kb.adjust(2, 2)
    return kb


# ===== /start =====


@router.message(CommandStart())
async def cmd_start(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
):
    user = message.from_user
    user_id = user.id if user else None
    username = user.username if user else None

    logger.info(
        "cmd_start_called user_id=%s username=%s",
        user_id,
        username,
    )

    profile = await get_profile(session, message.from_user.id)
    is_registered = profile is not None and profile.role is not None

    if is_registered:
        kb = build_main_menu_keyboard()

        await state.clear()
        await message.answer(
            "Привет! Ты уже в Link IT.",
            reply_markup=kb.as_markup(resize_keyboard=True),
        )

        logger.info(
            "cmd_start_existing_profile user_id=%s profile_id=%s role=%s",
            message.from_user.id,
            getattr(profile, "id", None),
            getattr(profile, "role", None),
        )
        return

    # Профиля ещё нет — создаём запись и запускаем ПЕРВИЧНУЮ регистрацию (без отмены)
    created_profile = await ensure_profile(session, message.from_user)
    logger.info(
        "cmd_start_new_profile_created user_id=%s profile_id=%s",
        message.from_user.id,
        getattr(created_profile, "id", None),
    )

    await start_profile_registration(message, state)
    logger.info(
        "cmd_start_profile_registration_started user_id=%s",
        message.from_user.id,
    )


@router.message(Command("help"))
async def cmd_help(message: Message):
    logger.info(
        "cmd_help_called user_id=%s username=%s",
        message.from_user.id if message.from_user else None,
        message.from_user.username if message.from_user else None,
    )
    await message.answer(
        "Основное:\n"
        "/start — главное меню или запуск регистрации, если профиля ещё нет\n"
        "/edit_profile — изменить профиль\n"
        "/profile — показать профиль\n\n"
        "Поиск людей и проектов доступен с кнопок меню внизу.\n",
    )


# ===== КНОПКИ МЕНЮ =====


@router.message(F.text == "👤 Профиль")
async def on_menu_profile(
    message: Message,
    session: AsyncSession,
    bot: Bot,
):
    logger.info(
        "menu_profile_clicked user_id=%s",
        message.from_user.id if message.from_user else None,
    )
    await cmd_profile(message, session, bot)


@router.message(F.text == "🆕 Новый проект")
async def on_menu_new_project(
    message: Message,
    state: FSMContext,
):
    logger.info(
        "menu_new_project_clicked user_id=%s",
        message.from_user.id if message.from_user else None,
    )
    # просто запускаем мастер регистрации проекта
    await start_project_registration(message, state)
