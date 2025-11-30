# handlers/projects/create.py

from types import SimpleNamespace

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from constants import (
    STACK_OPTIONS,
    ROLE_OPTIONS,
    PROJECT_STATUS_OPTIONS,
    PROJECT_STATUS_LABELS,
)
from views import format_project_card
from services import create_user_project

router = Router()

# Вспомогательные мапы код -> лейбл
STACK_CODE_TO_LABEL: dict[str, str] = {}
for group in STACK_OPTIONS.values():
    for label, code in group:
        STACK_CODE_TO_LABEL[code] = label

ROLE_CODE_TO_LABEL: dict[str, str] = {code: label for (label, code) in ROLE_OPTIONS}


class ProjectStates(StatesGroup):
    # создание
    photo = State()
    title = State()
    stack = State()
    stack_custom = State()
    idea = State()
    status = State()
    needs_now = State()
    looking_for = State()
    level = State()
    extra = State()
    team_limit = State()  # выбор: ввести число / пропустить
    team_limit_custom = State()  # ввод числа
    chat_link = State()
    confirm = State()

    # редактирование
    edit_title = State()
    edit_idea = State()
    edit_needs_now = State()
    edit_extra = State()
    edit_status = State()
    edit_level = State()
    edit_stack = State()
    edit_stack_custom = State()
    edit_looking_for = State()
    edit_team_limit = State()  # выбор: ввести число / пропустить
    edit_team_limit_custom = State()  # ввод числа при редактировании
    edit_chat_link = State()


# ===== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =====


def _build_preview_project_from_state(data: dict) -> SimpleNamespace:
    """
    Собираем "псевдо-проект" из FSM-данных,
    чтобы можно было использовать format_project_card без сохранения в БД.
    """
    return SimpleNamespace(
        title=data.get("title"),
        stack=data.get("stack"),
        idea=data.get("idea"),
        status=data.get("status", "idea"),
        needs_now=data.get("needs_now"),
        looking_for_role=data.get("looking_for_role"),
        level=data.get("level"),
        extra=data.get("extra"),
        team_limit=data.get("team_limit"),
        chat_link=data.get("chat_link"),
        image_file_id=data.get("image_file_id"),
    )


def _build_preview_keyboard() -> InlineKeyboardBuilder:
    """
    Клава под предпросмотром:
    - опубликовать,
    - перейти в меню редактирования,
    - отменить.
    """
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Опубликовать", callback_data="project_confirm:publish")
    kb.button(text="✏️ Редактировать", callback_data="proj_edit:menu")
    kb.button(text="❌ Отмена", callback_data="project_confirm:cancel")
    kb.adjust(1, 2)
    return kb


def _build_edit_menu_keyboard() -> InlineKeyboardBuilder:
    """
    Меню выбора, что именно редактировать.
    """
    kb = InlineKeyboardBuilder()
    kb.button(text="✏️ Название", callback_data="proj_edit:title")
    kb.button(text="✏️ Стек", callback_data="proj_edit:stack")
    kb.button(text="✏️ Идея", callback_data="proj_edit:idea")
    kb.button(text="✏️ Статус", callback_data="proj_edit:status")
    kb.button(text="✏️ Что сейчас нужно", callback_data="proj_edit:needs_now")
    kb.button(text="✏️ Кого ищем", callback_data="proj_edit:roles")
    kb.button(text="✏️ Уровень", callback_data="proj_edit:level")
    kb.button(text="✏️ Ожидания / формат", callback_data="proj_edit:extra")
    kb.button(text="✏️ Лимит команды", callback_data="proj_edit:team_limit")
    kb.button(text="✏️ Ссылка на чат", callback_data="proj_edit:chat_link")
    kb.button(text="⬅️ Назад", callback_data="proj_edit:back")
    kb.adjust(1, 2, 2, 2, 2, 2)
    return kb


async def _show_project_preview(message: Message, state: FSMContext):
    """
    Показываем предпросмотр проекта (с фото, если есть) + компактную клаву.
    """
    data = await state.get_data()
    preview_project = _build_preview_project_from_state(data)

    text = (
        "Проверь проект перед публикацией 👇\n\n"
        f"{format_project_card(preview_project)}"
    )
    kb = _build_preview_keyboard()

    await state.set_state(ProjectStates.confirm)

    if getattr(preview_project, "image_file_id", None):
        await message.answer_photo(
            photo=preview_project.image_file_id,
            caption=text,
            reply_markup=kb.as_markup(),
        )
    else:
        await message.answer(
            text,
            reply_markup=kb.as_markup(),
        )


# ===== СТАРТ СОЗДАНИЯ ПРОЕКТА =====


async def start_project_registration(message: Message, state: FSMContext):
    """
    Вызов этого метода — старт мастера создания проекта.
    Можно дергать из других хендлеров (меню и т.п.).
    """
    await state.clear()
    await state.set_state(ProjectStates.photo)

    kb = InlineKeyboardBuilder()
    kb.button(text="Пропустить фото", callback_data="project_skip_photo")
    kb.adjust(1)

    await message.answer(
        "Создаём новый проект.\n\n"
        "Шаг 1.\n"
        "Пришли обложку проекта (фото) или нажми «Пропустить фото».",
        reply_markup=kb.as_markup(),
    )


# ===== Шаг 1: фото =====


@router.message(ProjectStates.photo, F.photo)
async def project_photo_message(message: Message, state: FSMContext):
    file_id = message.photo[-1].file_id
    await state.update_data(image_file_id=file_id)
    await _ask_title(message, state)


@router.callback_query(ProjectStates.photo, F.data == "project_skip_photo")
async def project_photo_skip(callback: CallbackQuery, state: FSMContext):
    await _ask_title(callback.message, state)
    await callback.answer()


async def _ask_title(message: Message, state: FSMContext):
    await state.set_state(ProjectStates.title)
    await message.answer(
        "Шаг 2.\n"
        "Напиши короткое название проекта.\n"
        "Например: «Платформа для IT-нетворкинга»."
    )


# ===== Шаг 2: название =====


@router.message(ProjectStates.title, F.text)
async def project_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await state.update_data(stack_selected=[], stack_custom=None)
    await _ask_stack(message, state)


# ===== Шаг 3: стек (мультивыбор) =====


def _build_stack_keyboard(selected: list[str]) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    for group_key in ("backend", "frontend", "fullstack"):
        for label, code in STACK_OPTIONS.get(group_key, []):
            prefix = "✅ " if code in selected else ""
            kb.button(text=prefix + label, callback_data=f"project_stack:{code}")
    kb.button(text="Другое", callback_data="project_stack:other")
    kb.button(text="Готово", callback_data="project_stack:done")
    kb.adjust(2)
    return kb


async def _ask_stack(message: Message, state: FSMContext):
    await state.set_state(ProjectStates.stack)
    data = await state.get_data()
    selected = data.get("stack_selected", []) or []

    kb = _build_stack_keyboard(selected)

    await message.answer(
        "Шаг 3.\n"
        "Выбери стек проекта. Можно выбрать несколько вариантов.\n"
        "Если чего-то не хватает — нажми «Другое» и впиши.\n"
        "Когда закончишь — нажми «Готово».",
        reply_markup=kb.as_markup(),
    )


@router.callback_query(ProjectStates.stack, F.data.startswith("project_stack:"))
async def project_stack_callback(callback: CallbackQuery, state: FSMContext):
    _, code = callback.data.split(":", 1)
    data = await state.get_data()
    selected: list[str] = data.get("stack_selected", []) or []

    if code == "done":
        labels = [STACK_CODE_TO_LABEL.get(c, c) for c in selected]
        custom = data.get("stack_custom")
        parts: list[str] = []
        if labels:
            parts.append(", ".join(labels))
        if custom:
            parts.append(custom)
        final_stack = "; ".join(parts) if parts else None
        await state.update_data(stack=final_stack)

        await _ask_idea(callback.message, state)
        await callback.answer()
        return

    if code == "other":
        await state.set_state(ProjectStates.stack_custom)
        await callback.message.edit_text(
            "Напиши стек проекта текстом.\n"
            "Например: Python + React, Go + Vue, Node.js + React.",
        )
        await callback.answer()
        return

    # toggle выбора
    if code in selected:
        selected.remove(code)
    else:
        selected.append(code)

    await state.update_data(stack_selected=selected)

    kb = _build_stack_keyboard(selected)
    await callback.message.edit_text(
        "Шаг 3.\n"
        "Выбери стек проекта. Можно выбрать несколько вариантов.\n"
        "Если всё выбрал — нажми «Готово».",
        reply_markup=kb.as_markup(),
    )
    await callback.answer()


@router.message(ProjectStates.stack_custom, F.text)
async def project_stack_custom(message: Message, state: FSMContext):
    await state.update_data(stack_custom=message.text.strip())
    await _ask_stack(message, state)


async def _ask_idea(message: Message, state: FSMContext):
    await state.set_state(ProjectStates.idea)
    await message.answer(
        "Шаг 4.\n"
        "Опиши идею проекта и текущее состояние.\n"
        "Например: что уже сделано, какие технологии, чего хочешь достичь."
    )


# ===== Шаг 4: идея =====


@router.message(ProjectStates.idea, F.text)
async def project_idea(message: Message, state: FSMContext):
    await state.update_data(idea=message.text.strip())
    await _ask_status(message, state)


# ===== Шаг 5: статус проекта =====


async def _ask_status(message: Message, state: FSMContext):
    await state.set_state(ProjectStates.status)

    kb = InlineKeyboardBuilder()
    for label, code in PROJECT_STATUS_OPTIONS:
        kb.button(text=label, callback_data=f"project_status:{code}")
    kb.adjust(2)

    await message.answer(
        "Шаг 5.\n" "На какой стадии сейчас проект?\n" "Выбери статус:",
        reply_markup=kb.as_markup(),
    )


@router.callback_query(ProjectStates.status, F.data.startswith("project_status:"))
async def project_status_callback(
    callback: CallbackQuery,
    state: FSMContext,
):
    _, code = callback.data.split(":", 1)

    await state.update_data(status=code)

    status_label = PROJECT_STATUS_LABELS.get(code, code)
    await callback.answer(f"Статус: {status_label}", show_alert=False)

    await _ask_needs_now(callback.message, state)


# ===== Шаг 6: что сейчас нужно =====


async def _ask_needs_now(message: Message, state: FSMContext):
    await state.set_state(ProjectStates.needs_now)
    await message.answer(
        "Шаг 6.\n"
        "Расскажи, что <b>сейчас нужно</b> проекту:\n"
        "- какие роли ищешь;\n"
        "- какие задачи в приоритете;\n"
        "- что важно сделать в ближайшее время.\n\n"
        "Например: «Нужен backend-разработчик, чтобы поднять API, "
        "и дизайнер для первого экрана».",
    )


@router.message(ProjectStates.needs_now, F.text)
async def project_needs_now(message: Message, state: FSMContext):
    await state.update_data(needs_now=message.text.strip())
    await state.update_data(looking_selected=[])
    await _ask_looking_for(message, state)


# ===== Шаг 7: кого ищем (мультивыбор ролей) =====


def _build_looking_keyboard(selected: list[str]) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    for label, code in ROLE_OPTIONS:
        prefix = "✅ " if code in selected else ""
        kb.button(text=prefix + label, callback_data=f"project_role:{code}")
    kb.button(text="Пропустить", callback_data="project_role:skip")
    kb.button(text="Готово", callback_data="project_role:done")
    kb.adjust(2)
    return kb


async def _ask_looking_for(message: Message, state: FSMContext):
    await state.set_state(ProjectStates.looking_for)
    data = await state.get_data()
    selected = data.get("looking_selected", []) or []

    kb = _build_looking_keyboard(selected)

    await message.answer(
        "Шаг 7.\n"
        "Кого ты ищешь в проект? Можно выбрать несколько ролей.\n"
        "Если не хочешь указывать — нажми «Пропустить».",
        reply_markup=kb.as_markup(),
    )


@router.callback_query(ProjectStates.looking_for, F.data.startswith("project_role:"))
async def project_looking_for_callback(
    callback: CallbackQuery,
    state: FSMContext,
):
    _, code = callback.data.split(":", 1)
    data = await state.get_data()
    selected: list[str] = data.get("looking_selected", []) or []

    if code == "skip":
        await state.update_data(looking_for_role=None)
        await _ask_level(callback.message, state)
        await callback.answer()
        return

    if code == "done":
        labels = [ROLE_CODE_TO_LABEL.get(c, c) for c in selected]
        final_roles = ", ".join(labels) if labels else None
        await state.update_data(looking_for_role=final_roles)
        await _ask_level(callback.message, state)
        await callback.answer()
        return

    # toggle роли
    if code in selected:
        selected.remove(code)
    else:
        selected.append(code)

    await state.update_data(looking_selected=selected)

    kb = _build_looking_keyboard(selected)
    await callback.message.edit_text(
        "Шаг 7.\n"
        "Кого ты ищешь в проект? Можно выбрать несколько ролей.\n"
        "Когда закончишь — нажми «Готово».",
        reply_markup=kb.as_markup(),
    )
    await callback.answer()


# ===== Шаг 8: уровень =====


async def _ask_level(message: Message, state: FSMContext):
    await state.set_state(ProjectStates.level)

    kb = InlineKeyboardBuilder()
    kb.button(text="Junior", callback_data="project_level:junior")
    kb.button(text="Middle", callback_data="project_level:middle")
    kb.button(text="Senior", callback_data="project_level:senior")
    kb.button(text="Любой уровень", callback_data="project_level:any")
    kb.adjust(2)

    await message.edit_text(
        "Шаг 8.\n" "Какой уровень тебя больше всего интересует в этом проекте?",
        reply_markup=kb.as_markup(),
    )


@router.callback_query(ProjectStates.level, F.data.startswith("project_level:"))
async def project_level_callback(
    callback: CallbackQuery,
    state: FSMContext,
):
    _, code = callback.data.split(":", 1)
    mapping = {
        "junior": "Junior",
        "middle": "Middle",
        "senior": "Senior",
        "any": "Любой",
    }
    level_label = mapping.get(code, code)
    await state.update_data(level=level_label)

    await state.set_state(ProjectStates.extra)

    await callback.message.edit_text(
        "Шаг 9.\n"
        "Напиши важные детали: формат участия (вечера/выходные), "
        "занятость, нюансы.\n"
        "Если ничего добавлять не хочешь — напиши «-».",
    )
    await callback.answer()


# ===== Шаг 9: extra + переход к лимиту команды =====


@router.message(ProjectStates.extra, F.text)
async def project_extra(
    message: Message,
    state: FSMContext,
):
    extra = message.text.strip()
    if extra == "-":
        extra = None

    await state.update_data(extra=extra)
    await _ask_team_limit(message, state)


# ===== Шаг 10: лимит команды =====


def _build_team_limit_keyboard() -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(
        text="✏️ Ввести число людей",
        callback_data="project_team_limit:custom",
    )
    kb.button(
        text="Пропустить",
        callback_data="project_team_limit:skip",
    )
    kb.adjust(1, 1)
    return kb


async def _ask_team_limit(message: Message, state: FSMContext):
    await state.set_state(ProjectStates.team_limit)
    kb = _build_team_limit_keyboard()
    await message.answer(
        "Шаг 10.\n"
        "Сколько людей ты примерно ищешь в команду?\n\n"
        "Можно указать чёткое число (например, 3 или 5),\n"
        "или пока не указывать (если не уверен).",
        reply_markup=kb.as_markup(),
    )


@router.callback_query(
    ProjectStates.team_limit, F.data.startswith("project_team_limit:")
)
async def project_team_limit_callback(
    callback: CallbackQuery,
    state: FSMContext,
):
    _, code = callback.data.split(":", 1)

    if code == "skip":
        await state.update_data(team_limit=None)
        await callback.answer("Лимит по людям не указан", show_alert=False)
        await _ask_chat_link(callback.message, state)
        return

    if code == "custom":
        await state.set_state(ProjectStates.team_limit_custom)
        await callback.answer()
        await callback.message.answer(
            "Напиши, сколько людей тебе нужно в команду <b>числом</b>.\n\n"
            "Например: 3 или 5.\n"
            "Если передумал и не хочешь указывать — отправь «-».",
        )
        return


@router.message(ProjectStates.team_limit_custom, F.text)
async def project_team_limit_custom_message(
    message: Message,
    state: FSMContext,
):
    raw = (message.text or "").strip()

    if raw in ("-", "—", ""):
        await state.update_data(team_limit=None)
        await _ask_chat_link(message, state)
        return

    try:
        value = int(raw)
        if value <= 0:
            raise ValueError
    except ValueError:
        await message.answer(
            "Нужно указать положительное число.\n"
            "Например: 3 или 5.\n"
            "Или отправь «-», чтобы не указывать лимит."
        )
        return

    await state.update_data(team_limit=value)
    await _ask_chat_link(message, state)


# ===== Шаг 11: ссылка на чат =====


async def _ask_chat_link(message: Message, state: FSMContext):
    await state.set_state(ProjectStates.chat_link)

    kb = InlineKeyboardBuilder()
    kb.button(text="Пропустить", callback_data="project_chat_link:skip")
    kb.adjust(1)

    await message.answer(
        "Шаг 11.\n"
        "Если у проекта есть чат в Telegram или Discord — пришли ссылку.\n"
        "Например: https://t.me/your_project_chat\n\n"
        "Если чата пока нет — нажми «Пропустить» или отправь «-».",
        reply_markup=kb.as_markup(),
    )


@router.callback_query(ProjectStates.chat_link, F.data == "project_chat_link:skip")
async def project_chat_link_skip(
    callback: CallbackQuery,
    state: FSMContext,
):
    await state.update_data(chat_link=None)
    await callback.answer("Без ссылки на чат", show_alert=False)
    await _show_project_preview(callback.message, state)


@router.message(ProjectStates.chat_link, F.text)
async def project_chat_link_message(
    message: Message,
    state: FSMContext,
):
    raw = (message.text or "").strip()
    if raw in ("-", "—", ""):
        chat_link = None
    else:
        chat_link = raw

    await state.update_data(chat_link=chat_link)
    await _show_project_preview(message, state)


# ===== Предпросмотр: действия (публикация / отмена / меню редактирования) =====


@router.callback_query(F.data == "project_confirm:cancel")
async def project_confirm_cancel(
    callback: CallbackQuery,
    state: FSMContext,
):
    """
    Отмена публикации проекта на этапе предпросмотра:
    - чистим состояние,
    - удаляем сообщение с предпросмотром,
    - пишем короткое уведомление пользователю.
    """
    await state.clear()

    # Пытаемся удалить превью проекта
    try:
        await callback.message.delete()
    except Exception:
        pass

    # Сообщаем пользователю, что всё отменено
    # Реплай-клава с меню у тебя остаётся та же, что была.
    await callback.message.answer(
        "Создание проекта отменено.\n\n"
        "Если захочешь — нажми «🆕 Новый проект» и начни заново."
    )

    await callback.answer("Отмена создания проекта")


@router.callback_query(ProjectStates.confirm, F.data == "project_confirm:publish")
async def project_confirm_publish(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
):
    data = await state.get_data()
    await state.clear()

    image_file_id = data.get("image_file_id")
    title = data.get("title")
    stack = data.get("stack")
    idea = data.get("idea")
    status = data.get("status", "idea")
    needs_now = data.get("needs_now")
    looking_for_role = data.get("looking_for_role")
    level = data.get("level")
    extra = data.get("extra")
    team_limit = data.get("team_limit")
    chat_link = data.get("chat_link")

    project = await create_user_project(
        session,
        owner_telegram_id=callback.from_user.id,
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

    await callback.answer("Проект опубликован ✅", show_alert=False)

    final_text = (
        "Проект сохранён и добавлен в ленту.\n\n"
        "Его смогут увидеть другие пользователи в разделе «🚀 Лента проектов».\n\n"
        f"{format_project_card(project)}"
    )

    await callback.message.answer(final_text)


@router.callback_query(ProjectStates.confirm, F.data == "proj_edit:menu")
async def proj_edit_menu_callback(
    callback: CallbackQuery,
    state: FSMContext,
):
    kb = _build_edit_menu_keyboard()
    await callback.answer()
    await callback.message.answer(
        "Что именно хочешь отредактировать?",
        reply_markup=kb.as_markup(),
    )


@router.callback_query(ProjectStates.confirm, F.data == "proj_edit:back")
async def proj_edit_back_callback(
    callback: CallbackQuery,
    state: FSMContext,
):
    await callback.answer()
    try:
        await callback.message.delete()
    except Exception:
        pass

    await _show_project_preview(callback.message, state)


# ===== РЕДАКТИРОВАНИЕ: НАЗВАНИЕ =====


@router.callback_query(ProjectStates.confirm, F.data == "proj_edit:title")
async def proj_edit_title_callback(
    callback: CallbackQuery,
    state: FSMContext,
):
    data = await state.get_data()
    cur = data.get("title") or "—"

    await state.set_state(ProjectStates.edit_title)
    await callback.answer()
    await callback.message.answer(
        f"Текущее название:\n<b>{cur}</b>\n\n" "Напиши новое название проекта:",
    )


@router.message(ProjectStates.edit_title, F.text)
async def proj_edit_title_message(
    message: Message,
    state: FSMContext,
):
    await state.update_data(title=message.text.strip())
    await _show_project_preview(message, state)


# ===== РЕДАКТИРОВАНИЕ: ИДЕЯ =====


@router.callback_query(ProjectStates.confirm, F.data == "proj_edit:idea")
async def proj_edit_idea_callback(
    callback: CallbackQuery,
    state: FSMContext,
):
    data = await state.get_data()
    cur = data.get("idea") or "—"

    await state.set_state(ProjectStates.edit_idea)
    await callback.answer()
    await callback.message.answer(
        "Текущая идея проекта:\n" f"{cur}\n\n" "Отправь обновлённое описание идеи:",
    )


@router.message(ProjectStates.edit_idea, F.text)
async def proj_edit_idea_message(
    message: Message,
    state: FSMContext,
):
    await state.update_data(idea=message.text.strip())
    await _show_project_preview(message, state)


# ===== РЕДАКТИРОВАНИЕ: ЧТО СЕЙЧАС НУЖНО =====


@router.callback_query(ProjectStates.confirm, F.data == "proj_edit:needs_now")
async def proj_edit_needs_now_callback(
    callback: CallbackQuery,
    state: FSMContext,
):
    data = await state.get_data()
    cur = data.get("needs_now") or "—"

    await state.set_state(ProjectStates.edit_needs_now)
    await callback.answer()
    await callback.message.answer(
        "Сейчас в блоке «что нужно»:\n"
        f"{cur}\n\n"
        "Напиши, что сейчас нужно проекту:",
    )


@router.message(ProjectStates.edit_needs_now, F.text)
async def proj_edit_needs_now_message(
    message: Message,
    state: FSMContext,
):
    await state.update_data(needs_now=message.text.strip())
    await _show_project_preview(message, state)


# ===== РЕДАКТИРОВАНИЕ: EXTRA (ОЖИДАНИЯ / ФОРМАТ) =====


@router.callback_query(ProjectStates.confirm, F.data == "proj_edit:extra")
async def proj_edit_extra_callback(
    callback: CallbackQuery,
    state: FSMContext,
):
    data = await state.get_data()
    cur = data.get("extra") or "—"

    await state.set_state(ProjectStates.edit_extra)
    await callback.answer()
    await callback.message.answer(
        "Сейчас в блоке «ожидания / формат»:\n"
        f"{cur}\n\n"
        "Напиши, как хочешь это оформить сейчас.\n"
        "Если хочешь убрать этот блок — отправь «-».",
    )


@router.message(ProjectStates.edit_extra, F.text)
async def proj_edit_extra_message(
    message: Message,
    state: FSMContext,
):
    extra = message.text.strip()
    if extra == "-":
        extra = None
    await state.update_data(extra=extra)
    await _show_project_preview(message, state)


# ===== РЕДАКТИРОВАНИЕ: СТАТУС =====


@router.callback_query(ProjectStates.confirm, F.data == "proj_edit:status")
async def proj_edit_status_callback(
    callback: CallbackQuery,
    state: FSMContext,
):
    data = await state.get_data()
    cur_code = data.get("status", "idea")
    cur_label = PROJECT_STATUS_LABELS.get(cur_code, cur_code)

    await state.set_state(ProjectStates.edit_status)
    await callback.answer()
    kb = InlineKeyboardBuilder()
    for label, code in PROJECT_STATUS_OPTIONS:
        prefix = "✅ " if code == cur_code else ""
        kb.button(text=prefix + label, callback_data=f"project_status_edit:{code}")
    kb.adjust(2)

    await callback.message.answer(
        f"Текущий статус проекта: <b>{cur_label}</b>\n\n" "Выбери новый статус:",
        reply_markup=kb.as_markup(),
    )


@router.callback_query(
    ProjectStates.edit_status, F.data.startswith("project_status_edit:")
)
async def proj_edit_status_choice(
    callback: CallbackQuery,
    state: FSMContext,
):
    _, code = callback.data.split(":", 1)
    await state.update_data(status=code)
    await callback.answer()
    await _show_project_preview(callback.message, state)


# ===== РЕДАКТИРОВАНИЕ: СТЕК =====


@router.callback_query(ProjectStates.confirm, F.data == "proj_edit:stack")
async def proj_edit_stack_callback(
    callback: CallbackQuery,
    state: FSMContext,
):
    data = await state.get_data()
    cur = data.get("stack") or "—"

    await state.update_data(edit_stack_selected=[], edit_stack_custom=None)
    await state.set_state(ProjectStates.edit_stack)

    kb = _build_stack_keyboard([])
    await callback.answer()
    await callback.message.answer(
        f"Сейчас стек проекта:\n{cur}\n\n"
        "Выбери новый стек. Можно выбрать несколько вариантов.\n"
        "Когда закончишь — нажми «Готово».",
        reply_markup=kb.as_markup(),
    )


@router.callback_query(ProjectStates.edit_stack, F.data.startswith("project_stack:"))
async def proj_edit_stack_choice(
    callback: CallbackQuery,
    state: FSMContext,
):
    _, code = callback.data.split(":", 1)
    data = await state.get_data()
    selected: list[str] = data.get("edit_stack_selected", []) or []

    if code == "done":
        labels = [STACK_CODE_TO_LABEL.get(c, c) for c in selected]
        custom = data.get("edit_stack_custom")
        parts: list[str] = []
        if labels:
            parts.append(", ".join(labels))
        if custom:
            parts.append(custom)
        final_stack = "; ".join(parts) if parts else None
        await state.update_data(
            stack=final_stack,
            edit_stack_selected=[],
            edit_stack_custom=None,
        )
        await callback.answer()
        await _show_project_preview(callback.message, state)
        return

    if code == "other":
        await state.set_state(ProjectStates.edit_stack_custom)
        await callback.message.edit_text(
            "Напиши стек проекта текстом.\n"
            "Например: Python + React, Go + Vue, Node.js + React.",
        )
        await callback.answer()
        return

    # toggle
    if code in selected:
        selected.remove(code)
    else:
        selected.append(code)

    await state.update_data(edit_stack_selected=selected)

    kb = _build_stack_keyboard(selected)
    await callback.message.edit_text(
        "Выбери стек проекта. Можно выбрать несколько вариантов.\n"
        "Когда закончишь — нажми «Готово».",
        reply_markup=kb.as_markup(),
    )
    await callback.answer()


@router.message(ProjectStates.edit_stack_custom, F.text)
async def proj_edit_stack_custom_message(
    message: Message,
    state: FSMContext,
):
    await state.update_data(edit_stack_custom=message.text.strip())
    await state.set_state(ProjectStates.edit_stack)
    kb = _build_stack_keyboard(
        (await state.get_data()).get("edit_stack_selected", []) or []
    )
    await message.answer(
        "Учёл твой стек.\n"
        "Если хочешь — добавь варианты из списка ниже.\n"
        "Когда закончишь — нажми «Готово».",
        reply_markup=kb.as_markup(),
    )


# ===== РЕДАКТИРОВАНИЕ: КОГО ИЩЕМ =====


@router.callback_query(ProjectStates.confirm, F.data == "proj_edit:roles")
async def proj_edit_roles_callback(
    callback: CallbackQuery,
    state: FSMContext,
):
    data = await state.get_data()
    cur = data.get("looking_for_role") or "—"

    await state.update_data(edit_looking_selected=[])
    await state.set_state(ProjectStates.edit_looking_for)

    kb = _build_looking_keyboard([])
    await callback.answer()
    await callback.message.answer(
        f"Сейчас в блоке «кого ищем»:\n{cur}\n\n"
        "Выбери новые роли. Можно несколько.\n"
        "Когда закончишь — нажми «Готово», "
        "или «Пропустить», чтобы оставить пустым.",
        reply_markup=kb.as_markup(),
    )


@router.callback_query(
    ProjectStates.edit_looking_for, F.data.startswith("project_role:")
)
async def proj_edit_roles_choice(
    callback: CallbackQuery,
    state: FSMContext,
):
    _, code = callback.data.split(":", 1)
    data = await state.get_data()
    selected: list[str] = data.get("edit_looking_selected", []) or []

    if code == "skip":
        await state.update_data(
            looking_for_role=None,
            edit_looking_selected=[],
        )
        await callback.answer()
        await _show_project_preview(callback.message, state)
        return

    if code == "done":
        labels = [ROLE_CODE_TO_LABEL.get(c, c) for c in selected]
        final_roles = ", ".join(labels) if labels else None
        await state.update_data(
            looking_for_role=final_roles,
            edit_looking_selected=[],
        )
        await callback.answer()
        await _show_project_preview(callback.message, state)
        return

    # toggle
    if code in selected:
        selected.remove(code)
    else:
        selected.append(code)

    await state.update_data(edit_looking_selected=selected)

    kb = _build_looking_keyboard(selected)
    await callback.message.edit_text(
        "Кого ты ищешь в проект? Можно выбрать несколько ролей.\n"
        "Когда закончишь — нажми «Готово».",
        reply_markup=kb.as_markup(),
    )
    await callback.answer()


# ===== РЕДАКТИРОВАНИЕ: УРОВЕНЬ =====


@router.callback_query(ProjectStates.confirm, F.data == "proj_edit:level")
async def proj_edit_level_callback(
    callback: CallbackQuery,
    state: FSMContext,
):
    data = await state.get_data()
    cur = data.get("level") or "—"

    await state.set_state(ProjectStates.edit_level)
    await callback.answer()

    kb = InlineKeyboardBuilder()
    kb.button(text="Junior", callback_data="project_level_edit:junior")
    kb.button(text="Middle", callback_data="project_level_edit:middle")
    kb.button(text="Senior", callback_data="project_level_edit:senior")
    kb.button(text="Любой уровень", callback_data="project_level_edit:any")
    kb.adjust(2)

    await callback.message.answer(
        f"Сейчас в проекте указан уровень: <b>{cur}</b>\n\n"
        "Выбери новый уровень, который тебе интересен:",
        reply_markup=kb.as_markup(),
    )


@router.callback_query(
    ProjectStates.edit_level, F.data.startswith("project_level_edit:")
)
async def proj_edit_level_choice(
    callback: CallbackQuery,
    state: FSMContext,
):
    _, code = callback.data.split(":", 1)
    mapping = {
        "junior": "Junior",
        "middle": "Middle",
        "senior": "Senior",
        "any": "Любой",
    }
    level_label = mapping.get(code, code)
    await state.update_data(level=level_label)

    await callback.answer()
    await _show_project_preview(callback.message, state)


# ===== РЕДАКТИРОВАНИЕ: ЛИМИТ КОМАНДЫ =====


@router.callback_query(ProjectStates.confirm, F.data == "proj_edit:team_limit")
async def proj_edit_team_limit_callback(
    callback: CallbackQuery,
    state: FSMContext,
):
    data = await state.get_data()
    cur = data.get("team_limit")
    if cur is None:
        cur_label = "не указан"
    else:
        cur_label = str(cur)

    await state.set_state(ProjectStates.edit_team_limit)
    await callback.answer()

    kb = _build_team_limit_keyboard()
    await callback.message.answer(
        f"Сейчас лимит по людям: <b>{cur_label}</b>.\n\n"
        "Выбери — задать новое число или не указывать:",
        reply_markup=kb.as_markup(),
    )


@router.callback_query(
    ProjectStates.edit_team_limit, F.data.startswith("project_team_limit:")
)
async def proj_edit_team_limit_choice(
    callback: CallbackQuery,
    state: FSMContext,
):
    _, code = callback.data.split(":", 1)

    if code == "skip":
        await state.update_data(team_limit=None)
        await callback.answer("Лимит убран", show_alert=False)
        await _show_project_preview(callback.message, state)
        return

    if code == "custom":
        await state.set_state(ProjectStates.edit_team_limit_custom)
        await callback.answer()
        await callback.message.answer(
            "Напиши новый лимит по людям <b>числом</b>.\n"
            "Например: 3 или 5.\n"
            "Если хочешь убрать лимит — отправь «-».",
        )
        return


@router.message(ProjectStates.edit_team_limit_custom, F.text)
async def proj_edit_team_limit_custom_message(
    message: Message,
    state: FSMContext,
):
    raw = (message.text or "").strip()

    if raw in ("-", "—", ""):
        await state.update_data(team_limit=None)
        await _show_project_preview(message, state)
        return

    try:
        value = int(raw)
        if value <= 0:
            raise ValueError
    except ValueError:
        await message.answer(
            "Нужно указать положительное число.\n"
            "Например: 3 или 5.\n"
            "Или отправь «-», чтобы убрать лимит."
        )
        return

    await state.update_data(team_limit=value)
    await _show_project_preview(message, state)


# ===== РЕДАКТИРОВАНИЕ: ССЫЛКА НА ЧАТ =====


@router.callback_query(ProjectStates.confirm, F.data == "proj_edit:chat_link")
async def proj_edit_chat_link_callback(
    callback: CallbackQuery,
    state: FSMContext,
):
    data = await state.get_data()
    cur = data.get("chat_link") or "—"

    await state.set_state(ProjectStates.edit_chat_link)
    await callback.answer()
    await callback.message.answer(
        "Сейчас указана ссылка на чат:\n"
        f"{cur}\n\n"
        "Пришли новую ссылку на чат проекта в Telegram или Discord.\n"
        "Если хочешь убрать ссылку — отправь «-».",
    )


@router.message(ProjectStates.edit_chat_link, F.text)
async def proj_edit_chat_link_message(
    message: Message,
    state: FSMContext,
):
    raw = (message.text or "").strip()
    if raw in ("-", "—", ""):
        chat_link = None
    else:
        chat_link = raw

    await state.update_data(chat_link=chat_link)
    await _show_project_preview(message, state)
