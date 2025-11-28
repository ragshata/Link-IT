# handlers/start.py

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
    profile = await get_profile(session, message.from_user.id)
    is_registered = profile is not None and profile.role is not None

    if is_registered:
        kb = build_main_menu_keyboard()

        await state.clear()
        await message.answer(
            "Привет! Ты уже в LinkIT.\n\n"
            "Можешь:\n"
            "— посмотреть ленту разработчиков\n"
            "— посмотреть ленту проектов\n"
            "— создать новый проект\n"
            "— открыть свой профиль.",
            reply_markup=kb.as_markup(resize_keyboard=True),
        )
        return

    # Профиля ещё нет — создаём запись и запускаем ПЕРВИЧНУЮ регистрацию (без отмены)
    await ensure_profile(session, message.from_user)
    await start_profile_registration(message, state)


@router.message(Command("help"))
async def cmd_help(message: Message):
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
    await cmd_profile(message, session, bot)


@router.message(F.text == "🆕 Новый проект")
async def on_menu_new_project(
    message: Message,
    state: FSMContext,
):
    # просто запускаем мастер регистрации проекта
    await start_project_registration(message, state)
