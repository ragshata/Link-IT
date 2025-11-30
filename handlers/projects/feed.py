# handlers/projects/feed.py

from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from constants import ROLE_OPTIONS, STACK_OPTIONS
from views import format_project_card
from services import get_projects_feed, get_project

router = Router()

# Мапы код -> лейбл
ROLE_CODE_TO_LABEL = {code: label for (label, code) in ROLE_OPTIONS}

STACK_CODE_TO_LABEL: dict[str, str] = {}
for group in STACK_OPTIONS.values():
    for label, code in group:
        STACK_CODE_TO_LABEL[code] = label


class ProjectsFeedFilterStates(StatesGroup):
    choosing_filters = State()
    choosing_role = State()
    choosing_stack = State()
    choosing_level = State()


# ===== ВСПОМОГАЛКИ ДЛЯ ЛЕНТЫ =====


async def _send_project_card(
    *,
    source_message: Message,
    project,
    bot: Bot,
):
    text = format_project_card(project)

    kb = InlineKeyboardBuilder()
    kb.button(
        text="🤝 Откликнуться на проект",
        callback_data=f"proj_apply:{project.id}",
    )
    kb.button(
        text="⬅️ Предыдущий",
        callback_data="proj_prev",
    )
    kb.button(
        text="➡️ Следующий",
        callback_data="proj_next",
    )
    kb.adjust(1, 2)

    if getattr(project, "image_file_id", None):
        await bot.send_photo(
            chat_id=source_message.chat.id,
            photo=project.image_file_id,
            caption=text,
            reply_markup=kb.as_markup(),
        )
    else:
        await source_message.answer(
            text,
            reply_markup=kb.as_markup(),
        )


async def _get_projfeed_project_at_index(
    *,
    state: FSMContext,
    session: AsyncSession,
    requester_id: int,
    new_index: int,
):
    data = await state.get_data()
    ids: list[int] | None = data.get("projfeed_ids")

    if not ids:
        return None, None

    if new_index < 0 or new_index >= len(ids):
        return None, None

    project_id = ids[new_index]
    project = await get_project(session, project_id)
    if not project:
        return None, None

    # не показываем свои проекты (на всякий случай)
    if project.owner_telegram_id == requester_id:
        if new_index + 1 < len(ids):
            return await _get_projfeed_project_at_index(
                state=state,
                session=session,
                requester_id=requester_id,
                new_index=new_index + 1,
            )
        return None, None

    await state.update_data(projfeed_index=new_index)
    return project, new_index


# ===== ФИЛЬТРЫ ЛЕНТЫ =====


def _format_filters_summary(data: dict) -> str:
    role_code = data.get("proj_filter_role_code")
    stack_label = data.get("proj_filter_stack_label")
    level_label = data.get("proj_filter_level_label")

    parts: list[str] = []

    if role_code:
        parts.append(ROLE_CODE_TO_LABEL.get(role_code, role_code))
    if stack_label:
        parts.append(stack_label)
    if level_label:
        parts.append(level_label)

    if not parts:
        return "Фильтры: не выбраны — показываю все активные проекты."
    return "Фильтры: " + ", ".join(parts)


def _build_filters_keyboard() -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text="🎭 Роль в проекте", callback_data="proj_filt:role")
    kb.button(text="🧩 Стек", callback_data="proj_filt:stack")
    kb.button(text="📊 Уровень", callback_data="proj_filt:level")
    kb.button(text="♻️ Сбросить фильтры", callback_data="proj_filt:reset")
    kb.button(text="🔍 Показать ленту", callback_data="proj_filt:show")
    kb.adjust(1, 1, 1, 1, 1)
    return kb


@router.message(F.text == "🚀 Лента проектов")
async def projects_feed_handler(
    message: Message,
    state: FSMContext,
):
    """
    Старт ленты проектов — сначала показываем экран с фильтрами.
    """
    await state.clear()
    await state.set_state(ProjectsFeedFilterStates.choosing_filters)
    await state.update_data(
        proj_filter_role_code=None,
        proj_filter_stack_label=None,
        proj_filter_level_label=None,
    )

    data = await state.get_data()
    text = (
        "Как будем искать проекты? Можешь выбрать пару фильтров, "
        "а можно сразу смотреть ленту.\n\n" + _format_filters_summary(data)
    )
    kb = _build_filters_keyboard()
    await message.answer(text, reply_markup=kb.as_markup())


# --- выбор роли ---


@router.callback_query(
    ProjectsFeedFilterStates.choosing_filters, F.data == "proj_filt:role"
)
async def proj_filt_role_open(callback: CallbackQuery, state: FSMContext):
    kb = InlineKeyboardBuilder()
    for label, code in ROLE_OPTIONS:
        kb.button(text=label, callback_data=f"proj_filt_role:{code}")
    kb.button(text="❌ Сбросить роль", callback_data="proj_filt_role:clear")
    kb.button(text="⬅️ Назад", callback_data="proj_filt:back")
    kb.adjust(2, 1, 1)

    await callback.answer()
    await callback.message.edit_text(
        "Выбери, кого ты хочешь искать в проектах:",
        reply_markup=kb.as_markup(),
    )


@router.callback_query(F.data.startswith("proj_filt_role:"))
async def proj_filt_role_choose(callback: CallbackQuery, state: FSMContext):
    _, code = callback.data.split(":", 1)

    if code == "clear":
        await state.update_data(proj_filter_role_code=None)
    else:
        await state.update_data(proj_filter_role_code=code)

    await callback.answer()

    # Возвращаемся к общему экрану фильтров
    data = await state.get_data()
    text = (
        "Как будем искать проекты? Можешь выбрать пару фильтров, "
        "а можно сразу смотреть ленту.\n\n" + _format_filters_summary(data)
    )
    kb = _build_filters_keyboard()
    await state.set_state(ProjectsFeedFilterStates.choosing_filters)
    await callback.message.edit_text(text, reply_markup=kb.as_markup())


# --- выбор стека ---


def _build_stack_filter_keyboard() -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    # Берём популярные стеки (backend + frontend + fullstack)
    added = set()
    for group_key in ("backend", "frontend", "fullstack"):
        for label, code in STACK_OPTIONS.get(group_key, []):
            if code in added:
                continue
            added.add(code)
            kb.button(text=label, callback_data=f"proj_filt_stack:{code}")
    kb.button(text="❌ Сбросить стек", callback_data="proj_filt_stack:clear")
    kb.button(text="⬅️ Назад", callback_data="proj_filt:back")
    kb.adjust(2, 1, 1)
    return kb


@router.callback_query(
    ProjectsFeedFilterStates.choosing_filters, F.data == "proj_filt:stack"
)
async def proj_filt_stack_open(callback: CallbackQuery, state: FSMContext):
    kb = _build_stack_filter_keyboard()
    await callback.answer()
    await callback.message.edit_text(
        "Выбери основной стек, по которому будем искать проекты:",
        reply_markup=kb.as_markup(),
    )


@router.callback_query(F.data.startswith("proj_filt_stack:"))
async def proj_filt_stack_choose(callback: CallbackQuery, state: FSMContext):
    _, code = callback.data.split(":", 1)

    if code == "clear":
        await state.update_data(proj_filter_stack_label=None)
    else:
        label = STACK_CODE_TO_LABEL.get(code, code)
        await state.update_data(proj_filter_stack_label=label)

    await callback.answer()

    data = await state.get_data()
    text = (
        "Как будем искать проекты? Можешь выбрать пару фильтров, "
        "а можно сразу смотреть ленту.\n\n" + _format_filters_summary(data)
    )
    kb = _build_filters_keyboard()
    await state.set_state(ProjectsFeedFilterStates.choosing_filters)
    await callback.message.edit_text(text, reply_markup=kb.as_markup())


# --- выбор уровня ---


@router.callback_query(
    ProjectsFeedFilterStates.choosing_filters, F.data == "proj_filt:level"
)
async def proj_filt_level_open(callback: CallbackQuery, state: FSMContext):
    kb = InlineKeyboardBuilder()
    kb.button(text="Junior", callback_data="proj_filt_level:Junior")
    kb.button(text="Middle", callback_data="proj_filt_level:Middle")
    kb.button(text="Senior", callback_data="proj_filt_level:Senior")
    kb.button(text="Любой", callback_data="proj_filt_level:Любой")
    kb.button(text="❌ Сбросить уровень", callback_data="proj_filt_level:clear")
    kb.button(text="⬅️ Назад", callback_data="proj_filt:back")
    kb.adjust(2, 2, 1, 1)

    await callback.answer()
    await callback.message.edit_text(
        "Какой уровень ищем в проектах?",
        reply_markup=kb.as_markup(),
    )


@router.callback_query(F.data.startswith("proj_filt_level:"))
async def proj_filt_level_choose(callback: CallbackQuery, state: FSMContext):
    _, lvl = callback.data.split(":", 1)

    if lvl == "clear":
        await state.update_data(proj_filter_level_label=None)
    else:
        await state.update_data(proj_filter_level_label=lvl)

    await callback.answer()

    data = await state.get_data()
    text = (
        "Как будем искать проекты? Можешь выбрать пару фильтров, "
        "а можно сразу смотреть ленту.\n\n" + _format_filters_summary(data)
    )
    kb = _build_filters_keyboard()
    await state.set_state(ProjectsFeedFilterStates.choosing_filters)
    await callback.message.edit_text(text, reply_markup=kb.as_markup())


# --- назад и сброс ---


@router.callback_query(
    ProjectsFeedFilterStates.choosing_filters, F.data == "proj_filt:back"
)
async def proj_filt_back(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    text = (
        "Как будем искать проекты? Можешь выбрать пару фильтров, "
        "а можно сразу смотреть ленту.\n\n" + _format_filters_summary(data)
    )
    kb = _build_filters_keyboard()
    await callback.answer()
    await callback.message.edit_text(text, reply_markup=kb.as_markup())


@router.callback_query(
    ProjectsFeedFilterStates.choosing_filters, F.data == "proj_filt:reset"
)
async def proj_filt_reset(callback: CallbackQuery, state: FSMContext):
    await state.update_data(
        proj_filter_role_code=None,
        proj_filter_stack_label=None,
        proj_filter_level_label=None,
    )
    data = await state.get_data()

    text = "Фильтры сброшены.\n\n" + _format_filters_summary(data)
    kb = _build_filters_keyboard()
    await callback.answer()
    await callback.message.edit_text(text, reply_markup=kb.as_markup())


# --- показать ленту ---


@router.callback_query(
    ProjectsFeedFilterStates.choosing_filters, F.data == "proj_filt:show"
)
async def proj_filt_show(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession, bot: Bot
):
    data = await state.get_data()

    role_code = data.get("proj_filter_role_code")
    stack_label = data.get("proj_filter_stack_label")
    level_label = data.get("proj_filter_level_label")

    # Переводим код роли в человекочитаемый лейбл
    role_label: str | None = None
    if role_code:
        role_label = ROLE_CODE_TO_LABEL.get(role_code, role_code)

    # Для уровня, если выбрано "Любой", то вообще не фильтруем
    level_filter = level_label if level_label and level_label != "Любой" else None

    projects = await get_projects_feed(
        session,
        limit=50,
        requester_id=callback.from_user.id,
        role=role_label,
        stack=stack_label,
        level=level_filter,
    )

    if not projects:
        await callback.answer()
        await callback.message.edit_text(
            "По таким фильтрам пока нет проектов.\n"
            "Попробуй изменить фильтры или загляни позже."
        )
        return

    await state.update_data(
        projfeed_ids=[p.id for p in projects],
        projfeed_index=0,
    )

    await callback.answer()
    await callback.message.delete()

    await _send_project_card(
        source_message=callback.message,
        project=projects[0],
        bot=bot,
    )


# ===== ЛЕНТА: NEXT / PREV =====


@router.callback_query(F.data == "proj_next")
async def proj_next_callback(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
):
    data = await state.get_data()
    index: int | None = data.get("projfeed_index", 0)
    if index is None:
        index = 0

    new_index = index + 1
    project, _ = await _get_projfeed_project_at_index(
        state=state,
        session=session,
        requester_id=callback.from_user.id,
        new_index=new_index,
    )

    if not project:
        await callback.answer("Это был последний проект", show_alert=False)
        await callback.message.answer(
            "Ты посмотрел все проекты в ленте.\nЗагляни позже — появятся новые."
        )
        return

    await callback.answer()

    await _send_project_card(
        source_message=callback.message,
        project=project,
        bot=bot,
    )

    try:
        await callback.message.delete()
    except Exception:
        pass


@router.callback_query(F.data == "proj_prev")
async def proj_prev_callback(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
):
    data = await state.get_data()
    index: int | None = data.get("projfeed_index", 0)
    if index is None:
        index = 0

    new_index = index - 1
    if new_index < 0:
        await callback.answer("Это первый проект", show_alert=False)
        return

    project, _ = await _get_projfeed_project_at_index(
        state=state,
        session=session,
        requester_id=callback.from_user.id,
        new_index=new_index,
    )

    if not project:
        await callback.answer("Это первый проект", show_alert=False)
        return

    await callback.answer()

    await _send_project_card(
        source_message=callback.message,
        project=project,
        bot=bot,
    )

    try:
        await callback.message.delete()
    except Exception:
        pass
