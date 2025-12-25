# handlers/projects.py
import logging
from types import SimpleNamespace

from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from constants import (
    STACK_OPTIONS,
    ROLE_OPTIONS,
    STACK_LABELS,
    PROJECT_STATUS_OPTIONS,
    PROJECT_STATUS_LABELS,
)
from views import format_project_card, format_profile_public, html_safe
from services import (
    create_user_project,
    get_projects_feed,
    get_project,
    send_connection_request,
    get_profile,
)

router = Router()
logger = logging.getLogger(__name__)

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


# ===== ВСПОМОГАЛКИ =====


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
        image_file_id=data.get("image_file_id"),
    )


def _build_preview_keyboard() -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Опубликовать", callback_data="project_confirm:publish")
    kb.button(text="✏️ Название", callback_data="proj_edit:title")
    kb.button(text="✏️ Стек", callback_data="proj_edit:stack")
    kb.button(text="✏️ Идея", callback_data="proj_edit:idea")
    kb.button(text="✏️ Статус", callback_data="proj_edit:status")
    kb.button(text="✏️ Что сейчас нужно", callback_data="proj_edit:needs_now")
    kb.button(text="✏️ Кого ищем", callback_data="proj_edit:roles")
    kb.button(text="✏️ Уровень", callback_data="proj_edit:level")
    kb.button(text="✏️ Ожидания / формат", callback_data="proj_edit:extra")
    kb.button(text="❌ Отмена", callback_data="project_confirm:cancel")
    kb.adjust(1, 2, 2, 2, 2)
    return kb


async def _show_project_preview(message: Message, state: FSMContext):
    """
    Показываем предпросмотр проекта (с фото, если есть) + кнопки редактирования / публикации.
    """
    data = await state.get_data()
    preview_project = _build_preview_project_from_state(data)

    logger.info(
        "project_preview_shown user_id=%s title_len=%s has_image=%s status=%s",
        message.from_user.id if message.from_user else None,
        len(preview_project.title or "") if preview_project.title else 0,
        bool(getattr(preview_project, "image_file_id", None)),
        getattr(preview_project, "status", None),
    )

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


# ===== ЛЕНТА ПРОЕКТОВ (карточки) =====


async def _send_project_card(
    *,
    source_message: Message,
    project,
    bot: Bot,
):
    """
    Одна карточка проекта:
    - фото (если есть),
    - описание,
    - кнопки: отклик, предыдущий/следующий.
    """
    text = format_project_card(project)

    logger.info(
        "project_card_sent user_id=%s project_id=%s owner_id=%s has_image=%s",
        source_message.from_user.id if source_message.from_user else None,
        getattr(project, "id", None),
        getattr(project, "owner_telegram_id", None),
        bool(getattr(project, "image_file_id", None)),
    )

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
    """
    Берём проект по индексу из сохранённого списка.
    Своих проектов по желанию можно скипать.
    """
    data = await state.get_data()
    ids: list[int] | None = data.get("projfeed_ids")

    if not ids:
        logger.info(
            "projfeed_empty_ids requester_id=%s",
            requester_id,
        )
        return None, None

    if new_index < 0 or new_index >= len(ids):
        logger.info(
            "projfeed_index_out_of_range requester_id=%s new_index=%s total=%s",
            requester_id,
            new_index,
            len(ids),
        )
        return None, None

    project_id = ids[new_index]
    project = await get_project(session, project_id)
    if not project:
        logger.info(
            "projfeed_project_not_found requester_id=%s project_id=%s",
            requester_id,
            project_id,
        )
        return None, None

    # не показываем свои проекты
    if project.owner_telegram_id == requester_id:
        logger.info(
            "projfeed_skip_own_project requester_id=%s project_id=%s",
            requester_id,
            project_id,
        )
        if new_index + 1 < len(ids):
            return await _get_projfeed_project_at_index(
                state=state,
                session=session,
                requester_id=requester_id,
                new_index=new_index + 1,
            )
        return None, None

    await state.update_data(projfeed_index=new_index)

    logger.info(
        "projfeed_project_selected requester_id=%s project_id=%s index=%s",
        requester_id,
        project_id,
        new_index,
    )

    return project, new_index


# ===== старт регистрации проекта (вызывается из меню) =====


async def start_project_registration(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(ProjectStates.photo)

    logger.info(
        "project_registration_started user_id=%s",
        message.from_user.id if message.from_user else None,
    )

    kb = InlineKeyboardBuilder()
    kb.button(text="Пропустить фото", callback_data="project_skip_photo")
    kb.adjust(1)

    await message.answer(
        "Создаём новый проект.\n\n"
        "Шаг 1 из 8.\n"
        "Пришли обложку проекта (фото) или нажми «Пропустить фото».",
        reply_markup=kb.as_markup(),
    )


# ===== Шаг 1: фото =====


@router.message(ProjectStates.photo, F.photo)
async def project_photo_message(message: Message, state: FSMContext):
    file_id = message.photo[-1].file_id
    await state.update_data(image_file_id=file_id)

    logger.info(
        "project_photo_set user_id=%s",
        message.from_user.id if message.from_user else None,
    )

    await _ask_title(message, state)


@router.callback_query(ProjectStates.photo, F.data == "project_skip_photo")
async def project_photo_skip(callback: CallbackQuery, state: FSMContext):
    logger.info(
        "project_photo_skipped user_id=%s",
        callback.from_user.id,
    )
    await _ask_title(callback.message, state)
    await callback.answer()


async def _ask_title(message: Message, state: FSMContext):
    await state.set_state(ProjectStates.title)

    logger.info(
        "project_step_title user_id=%s",
        message.from_user.id if message.from_user else None,
    )

    await message.answer(
        "Шаг 2 из 8.\n"
        "Напиши короткое название проекта.\n"
        "Например: «Платформа для IT-нетворкинга».",
    )


# ===== Шаг 2: название =====


@router.message(ProjectStates.title, F.text)
async def project_title(message: Message, state: FSMContext):
    title = message.text.strip()
    await state.update_data(title=title)
    await state.update_data(stack_selected=[], stack_custom=None)

    logger.info(
        "project_title_set user_id=%s title_len=%s",
        message.from_user.id if message.from_user else None,
        len(title),
    )

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

    logger.info(
        "project_step_stack user_id=%s selected_count=%s",
        message.from_user.id if message.from_user else None,
        len(selected),
    )

    kb = _build_stack_keyboard(selected)

    await message.answer(
        "Шаг 3 из 8.\n"
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

        logger.info(
            "project_stack_done user_id=%s selected_count=%s has_custom=%s",
            callback.from_user.id,
            len(selected),
            bool(custom),
        )

        await _ask_idea(callback.message, state)
        await callback.answer()
        return

    if code == "other":
        await state.set_state(ProjectStates.stack_custom)

        logger.info(
            "project_stack_other_start user_id=%s selected_count=%s",
            callback.from_user.id,
            len(selected),
        )

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
        "Шаг 3 из 8.\n"
        "Выбери стек проекта. Можно выбрать несколько вариантов.\n"
        "Если всё выбрал — нажми «Готово».",
        reply_markup=kb.as_markup(),
    )
    await callback.answer()


@router.message(ProjectStates.stack_custom, F.text)
async def project_stack_custom(message: Message, state: FSMContext):
    text = message.text.strip()
    await state.update_data(stack_custom=text)

    logger.info(
        "project_stack_custom_entered user_id=%s text_len=%s",
        message.from_user.id if message.from_user else None,
        len(text),
    )

    await _ask_stack(message, state)


async def _ask_idea(message: Message, state: FSMContext):
    await state.set_state(ProjectStates.idea)

    logger.info(
        "project_step_idea user_id=%s",
        message.from_user.id if message.from_user else None,
    )

    await message.answer(
        "Шаг 4 из 8.\n"
        "Опиши идею проекта и текущее состояние.\n"
        "Например: что уже сделано, какие технологии, чего хочешь достичь.",
    )


# ===== Шаг 4: идея =====


@router.message(ProjectStates.idea, F.text)
async def project_idea(message: Message, state: FSMContext):
    idea = message.text.strip()
    await state.update_data(idea=idea)

    logger.info(
        "project_idea_set user_id=%s idea_len=%s",
        message.from_user.id if message.from_user else None,
        len(idea),
    )

    await _ask_status(message, state)


# ===== Шаг 5: статус проекта =====


async def _ask_status(message: Message, state: FSMContext):
    await state.set_state(ProjectStates.status)

    kb = InlineKeyboardBuilder()
    for label, code in PROJECT_STATUS_OPTIONS:
        kb.button(text=label, callback_data=f"project_status:{code}")
    kb.adjust(2)

    logger.info(
        "project_step_status user_id=%s",
        message.from_user.id if message.from_user else None,
    )

    await message.answer(
        "Шаг 5 из 8.\nНа какой стадии сейчас проект?\nВыбери статус:",
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

    logger.info(
        "project_status_set user_id=%s status=%s",
        callback.from_user.id,
        status_label,
    )

    await callback.answer(f"Статус: {status_label}", show_alert=False)

    await _ask_needs_now(callback.message, state)


# ===== Шаг 6: что сейчас нужно =====


async def _ask_needs_now(message: Message, state: FSMContext):
    await state.set_state(ProjectStates.needs_now)

    logger.info(
        "project_step_needs_now user_id=%s",
        message.from_user.id if message.from_user else None,
    )

    await message.answer(
        "Шаг 6 из 8.\n"
        "Расскажи, что <b>сейчас нужно</b> проекту:\n"
        "- какие роли ищешь;\n"
        "- какие задачи в приоритете;\n"
        "- что важно сделать в ближайшее время.\n\n"
        "Например: «Нужен backend-разработчик, чтобы поднять API, "
        "и дизайнер для первого экрана».",
    )


@router.message(ProjectStates.needs_now, F.text)
async def project_needs_now(message: Message, state: FSMContext):
    text = message.text.strip()
    await state.update_data(needs_now=text)
    await state.update_data(looking_selected=[])

    logger.info(
        "project_needs_now_set user_id=%s text_len=%s",
        message.from_user.id if message.from_user else None,
        len(text),
    )

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

    logger.info(
        "project_step_looking_for user_id=%s selected_count=%s",
        message.from_user.id if message.from_user else None,
        len(selected),
    )

    kb = _build_looking_keyboard(selected)

    await message.answer(
        "Шаг 7 из 8.\n"
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

        logger.info(
            "project_looking_for_skipped user_id=%s",
            callback.from_user.id,
        )

        await _ask_level(callback.message, state)
        await callback.answer()
        return

    if code == "done":
        labels = [ROLE_CODE_TO_LABEL.get(c, c) for c in selected]
        final_roles = ", ".join(labels) if labels else None
        await state.update_data(looking_for_role=final_roles)

        logger.info(
            "project_looking_for_done user_id=%s selected_count=%s",
            callback.from_user.id,
            len(selected),
        )

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
        "Шаг 7 из 8.\n"
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

    logger.info(
        "project_step_level user_id=%s",
        message.from_user.id if message.from_user else None,
    )

    await message.edit_text(
        "Шаг 8 из 8.\nКакой уровень тебя больше всего интересует в этом проекте?",
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

    logger.info(
        "project_level_set user_id=%s level=%s",
        callback.from_user.id,
        level_label,
    )

    await state.set_state(ProjectStates.extra)

    await callback.message.edit_text(
        "Финал.\n"
        "Напиши важные детали: формат участия (вечера/выходные), занятость, нюансы.\n"
        "Если ничего добавлять не хочешь — напиши «-».",
    )
    await callback.answer()


# ===== Финал: extra + ПРЕДПРОСМОТР =====


@router.message(ProjectStates.extra, F.text)
async def project_extra(
    message: Message,
    state: FSMContext,
):
    extra = message.text.strip()
    if extra == "-":
        extra = None

    await state.update_data(extra=extra)

    logger.info(
        "project_extra_set user_id=%s extra_len=%s",
        message.from_user.id if message.from_user else None,
        len(extra or ""),
    )

    await _show_project_preview(message, state)


# ===== Предпросмотр: действия =====


@router.callback_query(F.data == "project_confirm:cancel")
async def project_confirm_cancel(
    callback: CallbackQuery,
    state: FSMContext,
):
    logger.info(
        "project_publish_cancelled user_id=%s",
        callback.from_user.id,
    )

    await state.clear()

    try:
        await callback.message.delete()
    except Exception:
        logger.debug(
            "project_preview_delete_failed user_id=%s",
            callback.from_user.id,
            exc_info=True,
        )

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

    logger.info(
        "project_publish_attempt user_id=%s title_len=%s stack_len=%s idea_len=%s status=%s",
        callback.from_user.id,
        len(title or "") if title else 0,
        len(stack or "") if stack else 0,
        len(idea or "") if idea else 0,
        status,
    )

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
    )

    logger.info(
        "project_published user_id=%s project_id=%s status=%s",
        callback.from_user.id,
        getattr(project, "id", None),
        getattr(project, "status", None),
    )

    await callback.answer("Проект опубликован ✅", show_alert=False)

    final_text = (
        "Проект сохранён и добавлен в ленту.\n\n"
        "Его смогут увидеть другие пользователи в разделе «🚀 Лента проектов»."
    )

    await callback.message.answer(final_text)


# ===== РЕДАКТИРОВАНИЕ: НАЗВАНИЕ =====


@router.callback_query(ProjectStates.confirm, F.data == "proj_edit:title")
async def proj_edit_title_callback(
    callback: CallbackQuery,
    state: FSMContext,
):
    data = await state.get_data()
    cur = html_safe(data.get("title"), default="—")

    logger.info(
        "project_edit_title_start user_id=%s current_len=%s",
        callback.from_user.id,
        len(cur),
    )

    await state.set_state(ProjectStates.edit_title)
    await callback.answer()
    await callback.message.answer(
        f"Текущее название:\n<b>{cur}</b>\n\nНапиши новое название проекта:",
    )


@router.message(ProjectStates.edit_title, F.text)
async def proj_edit_title_message(
    message: Message,
    state: FSMContext,
):
    title = message.text.strip()
    await state.update_data(title=title)

    logger.info(
        "project_edit_title_set user_id=%s title_len=%s",
        message.from_user.id if message.from_user else None,
        len(title),
    )

    await _show_project_preview(message, state)


# ===== РЕДАКТИРОВАНИЕ: ИДЕЯ =====


@router.callback_query(ProjectStates.confirm, F.data == "proj_edit:idea")
async def proj_edit_idea_callback(
    callback: CallbackQuery,
    state: FSMContext,
):
    data = await state.get_data()
    cur = html_safe(data.get("idea"), default="—")

    logger.info(
        "project_edit_idea_start user_id=%s current_len=%s",
        callback.from_user.id,
        len(cur),
    )

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
    idea = message.text.strip()
    await state.update_data(idea=idea)

    logger.info(
        "project_edit_idea_set user_id=%s idea_len=%s",
        message.from_user.id if message.from_user else None,
        len(idea),
    )

    await _show_project_preview(message, state)


# ===== РЕДАКТИРОВАНИЕ: ЧТО СЕЙЧАС НУЖНО =====


@router.callback_query(ProjectStates.confirm, F.data == "proj_edit:needs_now")
async def proj_edit_needs_now_callback(
    callback: CallbackQuery,
    state: FSMContext,
):
    data = await state.get_data()
    cur = html_safe(data.get("needs_now"), default="—")

    logger.info(
        "project_edit_needs_now_start user_id=%s current_len=%s",
        callback.from_user.id,
        len(cur),
    )

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
    text = message.text.strip()
    await state.update_data(needs_now=text)

    logger.info(
        "project_edit_needs_now_set user_id=%s text_len=%s",
        message.from_user.id if message.from_user else None,
        len(text),
    )

    await _show_project_preview(message, state)


# ===== РЕДАКТИРОВАНИЕ: EXTRA (ОЖИДАНИЯ / ФОРМАТ) =====


@router.callback_query(ProjectStates.confirm, F.data == "proj_edit:extra")
async def proj_edit_extra_callback(
    callback: CallbackQuery,
    state: FSMContext,
):
    data = await state.get_data()
    cur = html_safe(data.get("extra"), default="—")

    logger.info(
        "project_edit_extra_start user_id=%s current_len=%s",
        callback.from_user.id,
        len(cur),
    )

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

    logger.info(
        "project_edit_extra_set user_id=%s extra_len=%s",
        message.from_user.id if message.from_user else None,
        len(extra or ""),
    )

    await _show_project_preview(message, state)


# ===== РЕДАКТИРОВАНИЕ: СТАТУС =====


@router.callback_query(ProjectStates.confirm, F.data == "proj_edit:status")
async def proj_edit_status_callback(
    callback: CallbackQuery,
    state: FSMContext,
):
    data = await state.get_data()
    cur_code = data.get("status", "idea")
    cur_label = html_safe(PROJECT_STATUS_LABELS.get(cur_code, cur_code))

    logger.info(
        "project_edit_status_start user_id=%s current_status=%s",
        callback.from_user.id,
        cur_label,
    )

    await state.set_state(ProjectStates.edit_status)
    await callback.answer()
    kb = InlineKeyboardBuilder()
    for label, code in PROJECT_STATUS_OPTIONS:
        prefix = "✅ " if code == cur_code else ""
        kb.button(text=prefix + label, callback_data=f"project_status_edit:{code}")
    kb.adjust(2)

    await callback.message.answer(
        f"Текущий статус проекта: <b>{cur_label}</b>\n\nВыбери новый статус:",
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

    logger.info(
        "project_edit_status_set user_id=%s status=%s",
        callback.from_user.id,
        PROJECT_STATUS_LABELS.get(code, code),
    )

    await callback.answer()
    await _show_project_preview(callback.message, state)


# ===== РЕДАКТИРОВАНИЕ: СТЕК =====


@router.callback_query(ProjectStates.confirm, F.data == "proj_edit:stack")
async def proj_edit_stack_callback(
    callback: CallbackQuery,
    state: FSMContext,
):
    data = await state.get_data()
    cur = html_safe(data.get("stack"), default="—")

    logger.info(
        "project_edit_stack_start user_id=%s current_len=%s",
        callback.from_user.id,
        len(cur),
    )

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

        logger.info(
            "project_edit_stack_done user_id=%s selected_count=%s has_custom=%s",
            callback.from_user.id,
            len(selected),
            bool(custom),
        )

        await callback.answer()
        await _show_project_preview(callback.message, state)
        return

    if code == "other":
        await state.set_state(ProjectStates.edit_stack_custom)

        logger.info(
            "project_edit_stack_other_start user_id=%s selected_count=%s",
            callback.from_user.id,
            len(selected),
        )

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
    text = message.text.strip()
    await state.update_data(edit_stack_custom=text)

    logger.info(
        "project_edit_stack_custom_entered user_id=%s text_len=%s",
        message.from_user.id if message.from_user else None,
        len(text),
    )

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
    cur = html_safe(data.get("looking_for_role"), default="—")

    logger.info(
        "project_edit_roles_start user_id=%s current_len=%s",
        callback.from_user.id,
        len(cur),
    )

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

        logger.info(
            "project_edit_roles_skipped user_id=%s",
            callback.from_user.id,
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

        logger.info(
            "project_edit_roles_done user_id=%s selected_count=%s",
            callback.from_user.id,
            len(selected),
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
    cur = html_safe(data.get("level"), default="—")

    logger.info(
        "project_edit_level_start user_id=%s current_level=%s",
        callback.from_user.id,
        cur,
    )

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

    logger.info(
        "project_edit_level_set user_id=%s level=%s",
        callback.from_user.id,
        level_label,
    )

    await callback.answer()
    await _show_project_preview(callback.message, state)


# ===== Лента проектов (кнопка в меню) =====


@router.message(F.text == "🚀 Лента проектов")
async def projects_feed_handler(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
):
    logger.info(
        "projects_feed_opened user_id=%s",
        message.from_user.id if message.from_user else None,
    )

    projects = await get_projects_feed(session, limit=50)

    projects = [p for p in projects if p.owner_telegram_id != message.from_user.id]

    if not projects:
        logger.info(
            "projects_feed_empty user_id=%s",
            message.from_user.id if message.from_user else None,
        )
        await message.answer(
            "Пока нет проектов в ленте.\n"
            "Будь первым — создай свой через «🆕 Новый проект».",
        )
        return

    await state.update_data(
        projfeed_ids=[p.id for p in projects],
        projfeed_index=0,
    )

    logger.info(
        "projects_feed_loaded user_id=%s count=%s",
        message.from_user.id if message.from_user else None,
        len(projects),
    )

    await _send_project_card(
        source_message=message,
        project=projects[0],
        bot=bot,
    )


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

    logger.info(
        "projects_feed_next user_id=%s current_index=%s new_index=%s",
        callback.from_user.id,
        index,
        new_index,
    )

    project, _ = await _get_projfeed_project_at_index(
        state=state,
        session=session,
        requester_id=callback.from_user.id,
        new_index=new_index,
    )

    if not project:
        logger.info(
            "projects_feed_reached_end user_id=%s",
            callback.from_user.id,
        )
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
        logger.debug(
            "projects_feed_prev_message_delete_failed user_id=%s",
            callback.from_user.id,
            exc_info=True,
        )


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

    logger.info(
        "projects_feed_prev user_id=%s current_index=%s new_index=%s",
        callback.from_user.id,
        index,
        new_index,
    )

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
        logger.debug(
            "projects_feed_prev_message_delete_failed user_id=%s",
            callback.from_user.id,
            exc_info=True,
        )


@router.callback_query(F.data.startswith("proj_apply:"))
async def proj_apply_callback(
    callback: CallbackQuery,
    session: AsyncSession,
    bot: Bot,
):
    _, raw_id = callback.data.split(":", 1)
    try:
        project_id = int(raw_id)
    except ValueError:
        logger.warning(
            "project_apply_invalid_project_id user_id=%s raw_id=%s",
            callback.from_user.id,
            raw_id,
        )
        await callback.answer("Что-то пошло не так", show_alert=True)
        return

    project = await get_project(session, project_id)
    if not project:
        logger.info(
            "project_apply_project_not_found user_id=%s project_id=%s",
            callback.from_user.id,
            project_id,
        )
        await callback.answer("Проект не найден", show_alert=True)
        return

    from_id = callback.from_user.id
    to_id = project.owner_telegram_id

    logger.info(
        "project_apply_attempt user_id=%s project_id=%s owner_id=%s",
        from_id,
        project_id,
        to_id,
    )

    req, reason = await send_connection_request(
        session,
        from_id=from_id,
        to_id=to_id,
    )

    if reason == "self":
        logger.info(
            "project_apply_self user_id=%s project_id=%s",
            from_id,
            project_id,
        )
        await callback.answer("Это твой проект 😄", show_alert=True)
        return

    if reason == "exists":
        logger.info(
            "project_apply_exists user_id=%s project_id=%s request_id=%s",
            from_id,
            project_id,
            getattr(req, "id", None),
        )
        await callback.answer(
            "Ты уже откликался на этот проект. Ждём ответа.",
            show_alert=False,
        )
        return

    if reason == "limit":
        logger.info(
            "project_apply_limit_reached user_id=%s project_id=%s",
            from_id,
            project_id,
        )
        await callback.answer(
            "Ты уже отправил максимум заявок на сегодня. Попробуй завтра 🙂",
            show_alert=True,
        )
        return

    await callback.answer("Заявка на проект отправлена 🎯", show_alert=False)

    applicant_profile = await get_profile(session, from_id)
    applicant_text = format_profile_public(applicant_profile)
    project_text = format_project_card(project)

    notify_text = (
        "На твой проект в Link IT пришла новая заявка.\n\n"
        f"Проект:\n{project_text}\n\n"
        "Кандидат:\n\n"
        f"{applicant_text}\n\n"
        "Контакты откликнувшегося откроются, если ты примешь заявку."
    )

    kb = InlineKeyboardBuilder()
    kb.button(
        text="✅ Принять",
        callback_data=f"conn_accept:{req.id}",
    )
    kb.button(
        text="❌ Отклонить",
        callback_data=f"conn_reject:{req.id}",
    )
    kb.adjust(2)

    try:
        if applicant_profile and applicant_profile.avatar_file_id:
            await bot.send_photo(
                chat_id=to_id,
                photo=applicant_profile.avatar_file_id,
                caption=notify_text,
                reply_markup=kb.as_markup(),
            )
        else:
            await bot.send_message(
                chat_id=to_id,
                text=notify_text,
                reply_markup=kb.as_markup(),
            )

        logger.info(
            "project_apply_notification_sent user_id=%s owner_id=%s project_id=%s request_id=%s",
            from_id,
            to_id,
            project_id,
            getattr(req, "id", None),
        )
    except Exception:
        logger.debug(
            "project_apply_notification_failed user_id=%s owner_id=%s project_id=%s request_id=%s",
            from_id,
            to_id,
            project_id,
            getattr(req, "id", None),
            exc_info=True,
        )

    await callback.message.answer(
        "Заявка на участие в проекте отправлена.\n\n"
        "Когда владелец проекта ответит, я пришлю тебе уведомление: "
        "либо контакты, либо отказ."
    )
