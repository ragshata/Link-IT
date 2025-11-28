# handlers/projects.py

from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from constants import STACK_OPTIONS, ROLE_OPTIONS, STACK_LABELS
from views import format_project_card, format_profile_public
from services import (
    create_user_project,
    get_projects_feed,
    get_project,
    send_connection_request,
    get_profile,
)

router = Router()


# Вспомогательные мапы код -> лейбл
STACK_CODE_TO_LABEL: dict[str, str] = {}
for group in STACK_OPTIONS.values():
    for label, code in group:
        STACK_CODE_TO_LABEL[code] = label

ROLE_CODE_TO_LABEL: dict[str, str] = {code: label for (label, code) in ROLE_OPTIONS}


class ProjectStates(StatesGroup):
    photo = State()
    title = State()
    stack = State()
    stack_custom = State()
    idea = State()
    looking_for = State()
    level = State()
    extra = State()


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

    if project.image_file_id:
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
        return None, None

    if new_index < 0 or new_index >= len(ids):
        return None, None

    project_id = ids[new_index]
    project = await get_project(session, project_id)
    if not project:
        return None, None

    # опционально: не показываем свои проекты
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


# ===== старт регистрации проекта (вызывается из меню) =====


async def start_project_registration(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(ProjectStates.photo)

    kb = InlineKeyboardBuilder()
    kb.button(text="Пропустить фото", callback_data="project_skip_photo")
    kb.adjust(1)

    await message.answer(
        "Создаём новый проект.\n\n"
        "Шаг 1 из 6.\n"
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
        "Шаг 2 из 6.\n"
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
    # Берём backend + frontend + fullstack, чтобы было достаточно вариантов
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
        "Шаг 3 из 6.\n"
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
        # финализируем выбор
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
            "Например: Python + React, Go + Vue, Node.js + React."
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
        "Шаг 3 из 6.\n"
        "Выбери стек проекта. Можно выбрать несколько вариантов.\n"
        "Если всё выбрал — нажми «Готово».",
        reply_markup=kb.as_markup(),
    )
    await callback.answer()


@router.message(ProjectStates.stack_custom, F.text)
async def project_stack_custom(message: Message, state: FSMContext):
    await state.update_data(stack_custom=message.text.strip())
    # возвращаемся к мультивыбору стека
    await _ask_stack(message, state)


async def _ask_idea(message: Message, state: FSMContext):
    await state.set_state(ProjectStates.idea)
    await message.answer(
        "Шаг 4 из 6.\n"
        "Опиши идею проекта и текущее состояние.\n"
        "Например: что уже сделано, какие технологии, чего хочешь достичь."
    )


# ===== Шаг 4: идея =====


@router.message(ProjectStates.idea, F.text)
async def project_idea(message: Message, state: FSMContext):
    await state.update_data(idea=message.text.strip())
    await state.update_data(looking_selected=[])
    await _ask_looking_for(message, state)


# ===== Шаг 5: кого ищем (мультивыбор ролей) =====


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
        "Шаг 5 из 6.\n"
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
        "Шаг 5 из 6.\n"
        "Кого ты ищешь в проект? Можно выбрать несколько ролей.\n"
        "Когда закончишь — нажми «Готово».",
        reply_markup=kb.as_markup(),
    )
    await callback.answer()


# ===== Шаг 6: уровень (junior/middle/senior) =====


async def _ask_level(message: Message, state: FSMContext):
    await state.set_state(ProjectStates.level)

    kb = InlineKeyboardBuilder()
    kb.button(text="Junior", callback_data="project_level:junior")
    kb.button(text="Middle", callback_data="project_level:middle")
    kb.button(text="Senior", callback_data="project_level:senior")
    kb.button(text="Любой уровень", callback_data="project_level:any")
    kb.adjust(2)

    await message.edit_text(
        "Шаг 6 из 6.\n" "Какой уровень тебя больше всего интересует в этом проекте?",
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
        "Финал.\n"
        "Напиши важные детали: формат участия (вечера/выходные), занятость, нюансы.\n"
        "Если ничего добавлять не хочешь — напиши «-».",
    )
    await callback.answer()


# ===== Финал: extra + сохранение =====


@router.message(ProjectStates.extra, F.text)
async def project_extra(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
):
    extra = message.text.strip()
    if extra == "-":
        extra = None

    await state.update_data(extra=extra)
    data = await state.get_data()
    await state.clear()

    image_file_id = data.get("image_file_id")
    title = data.get("title")
    stack = data.get("stack")
    idea = data.get("idea")
    looking_for_role = data.get("looking_for_role")
    level = data.get("level")
    extra = data.get("extra")

    await create_user_project(
        session,
        owner_telegram_id=message.from_user.id,
        title=title,
        stack=stack,
        idea=idea,
        looking_for_role=looking_for_role,
        level=level,
        extra=extra,
        image_file_id=image_file_id,
    )

    await message.answer(
        "Проект сохранён и добавлен в ленту.\n\n"
        "Его смогут увидеть другие пользователи в разделе «🚀 Лента проектов»."
    )


# ===== Лента проектов (кнопка в меню) =====


@router.message(F.text == "🚀 Лента проектов")
async def projects_feed_handler(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
):
    projects = await get_projects_feed(session, limit=50)

    # можно не показывать свои проекты
    projects = [p for p in projects if p.owner_telegram_id != message.from_user.id]

    if not projects:
        await message.answer(
            "Пока нет проектов в ленте.\n"
            "Будь первым — создай свой через «🆕 Новый проект»."
        )
        return

    await state.update_data(
        projfeed_ids=[p.id for p in projects],
        projfeed_index=0,
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
    project, _ = await _get_projfeed_project_at_index(
        state=state,
        session=session,
        requester_id=callback.from_user.id,
        new_index=new_index,
    )

    if not project:
        await callback.answer("Это был последний проект", show_alert=False)
        await callback.message.answer(
            "Ты посмотрел все проекты в ленте.\n" "Загляни позже — появятся новые."
        )
        return

    await callback.answer()

    # шлём НОВУЮ карточку
    await _send_project_card(
        source_message=callback.message,
        project=project,
        bot=bot,
    )

    # удаляем старую карточку
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

    # шлём НОВУЮ карточку
    await _send_project_card(
        source_message=callback.message,
        project=project,
        bot=bot,
    )

    # удаляем старую
    try:
        await callback.message.delete()
    except Exception:
        pass


@router.callback_query(F.data.startswith("proj_apply:"))
async def proj_apply_callback(
    callback: CallbackQuery,
    session: AsyncSession,
    bot: Bot,
):
    """
    Отклик на проект:
    - создаём ConnectionRequest между откликнувшимся и владельцем проекта,
    - владельцу уходит уведомление с фоткой и описанием откликнувшегося,
      контакты скрыты до принятия.
    """
    _, raw_id = callback.data.split(":", 1)
    try:
        project_id = int(raw_id)
    except ValueError:
        await callback.answer("Что-то пошло не так", show_alert=True)
        return

    project = await get_project(session, project_id)
    if not project:
        await callback.answer("Проект не найден", show_alert=True)
        return

    from_id = callback.from_user.id
    to_id = project.owner_telegram_id

    req, reason = await send_connection_request(
        session,
        from_id=from_id,
        to_id=to_id,
    )

    if reason == "self":
        await callback.answer("Это твой проект 😄", show_alert=True)
        return

    if reason == "exists":
        await callback.answer(
            "Ты уже откликался на этот проект. Ждём ответа.",
            show_alert=False,
        )
        return

    await callback.answer("Заявка на проект отправлена 🎯", show_alert=False)

    applicant_profile = await get_profile(session, from_id)
    applicant_text = format_profile_public(applicant_profile)
    project_text = format_project_card(project)

    notify_text = (
        "На твой проект в LinkIT пришла новая заявка.\n\n"
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
    except Exception:
        pass

    await callback.message.answer(
        "Заявка на участие в проекте отправлена.\n\n"
        "Когда владелец проекта ответит, я пришлю тебе уведомление: "
        "либо контакты, либо отказ."
    )
