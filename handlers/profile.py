from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from services import get_profile, update_profile_data
from views import format_profile_text
from constants import (
    ROLE_OPTIONS,
    STACK_OPTIONS,
    FRAMEWORK_OPTIONS,
    SKILL_OPTIONS,
    GOAL_OPTIONS,
)

router = Router()

PROFILE_CANCEL_CB = "profile_cancel_edit"


class RegistrationStates(StatesGroup):
    name = State()
    avatar = State()
    role = State()
    stack = State()  # язык/стек
    framework = State()  # выбор фреймворка(ов)
    skills = State()  # выбор навыков (инлайн)
    skills_custom = State()  # ввод своих навыков текстом
    goals = State()
    about = State()


# ===== ВСПОМОГАТЕЛЬНЫЕ УТИЛЫ =====


def _build_frameworks_keyboard_fullstack(
    stack_code: str,
    selected: list[str],
    is_edit: bool,
) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    fw_options = FRAMEWORK_OPTIONS.get(stack_code, [])
    for text, code in fw_options:
        prefix = "✅ " if code in selected else ""
        kb.button(text=prefix + text, callback_data=f"framework_multi:{code}")
    kb.button(text="Другое", callback_data="framework_multi:other")
    kb.button(text="Готово", callback_data="framework_multi:done")
    if is_edit:
        kb.button(text="Отменить редактирование", callback_data=PROFILE_CANCEL_CB)
    kb.adjust(2)
    return kb


def _build_skills_keyboard(
    selected: list[str],
    is_edit: bool,
) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    for label, code in SKILL_OPTIONS:
        if code in ("other", "done"):
            kb.button(text=label, callback_data=f"skill:{code}")
        else:
            prefix = "✅ " if code in selected else ""
            kb.button(text=prefix + label, callback_data=f"skill:{code}")
    if is_edit:
        kb.button(text="Отменить редактирование", callback_data=PROFILE_CANCEL_CB)
    kb.adjust(2)
    return kb


async def _start_profile_flow(
    message: Message,
    state: FSMContext,
    *,
    allow_cancel: bool,
):
    """Общий старт регистрации/редактирования профиля."""
    await state.clear()
    await state.set_state(RegistrationStates.name)
    await state.update_data(is_edit=allow_cancel)

    kb = InlineKeyboardBuilder()
    kb.button(text="Взять имя из Telegram", callback_data="name_from_tg")
    if allow_cancel:
        kb.button(text="Отменить редактирование", callback_data=PROFILE_CANCEL_CB)
    kb.adjust(1)

    await message.answer(
        "Давай заполним профиль.\n\n"
        "Шаг 1 из 7.\n"
        "Введи имя, которое будем показывать в профиле, "
        "или нажми кнопку ниже, чтобы взять имя из Telegram.",
        reply_markup=kb.as_markup(),
    )


# Это нужно вызывать при ПЕРВОЙ регистрации (например, из /start)
async def start_profile_registration(message: Message, state: FSMContext):
    await _start_profile_flow(message, state, allow_cancel=False)


# Это /edit_profile и кнопка ✏️ Редактировать в профиле
@router.message(Command("edit_profile"))
async def cmd_edit_profile(message: Message, state: FSMContext):
    await _start_profile_flow(message, state, allow_cancel=True)


# ===== Команда /profile =====


@router.message(Command("profile"))
async def cmd_profile(message: Message, session: AsyncSession, bot: Bot):
    profile = await get_profile(session, message.from_user.id)

    if not profile:
        await message.answer(
            "Профиль ещё не заполнен. Используй /edit_profile, чтобы пройти регистрацию."
        )
        return

    text = format_profile_text(
        profile,
        fallback_username=message.from_user.username,
    )

    kb = InlineKeyboardBuilder()
    kb.button(text="🏆 Награды", callback_data="profile_rewards")
    kb.button(text="✏️ Редактировать", callback_data="profile_edit")
    kb.adjust(2)

    if profile.avatar_file_id:
        await bot.send_photo(
            chat_id=message.chat.id,
            photo=profile.avatar_file_id,
            caption=text,
            reply_markup=kb.as_markup(),
        )
    else:
        await message.answer(
            text,
            reply_markup=kb.as_markup(),
        )


# ===== Шаг 1: имя =====


@router.message(RegistrationStates.name, F.text)
async def process_name_text(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await _ask_avatar(message, state)


@router.callback_query(RegistrationStates.name, F.data == "name_from_tg")
async def process_name_from_tg(
    callback: CallbackQuery,
    state: FSMContext,
):
    tg_name = callback.from_user.first_name or ""
    await state.update_data(name=tg_name)
    await _ask_avatar(callback.message, state)
    await callback.answer()


async def _ask_avatar(message: Message, state: FSMContext):
    await state.set_state(RegistrationStates.avatar)
    data = await state.get_data()
    is_edit = data.get("is_edit", False)

    kb = InlineKeyboardBuilder()
    kb.button(text="Взять фото из Telegram", callback_data="avatar_from_tg")
    kb.button(text="Пропустить", callback_data="avatar_skip")
    if is_edit:
        kb.button(text="Отменить редактирование", callback_data=PROFILE_CANCEL_CB)
    kb.adjust(1)

    await message.answer(
        "Шаг 2 из 7.\n"
        "Отправь фото, которое будем считать аватаром в LinkIT, "
        "или выбери один из вариантов ниже.",
        reply_markup=kb.as_markup(),
    )


# ===== Шаг 2: аватар =====


@router.message(RegistrationStates.avatar, F.photo)
async def process_avatar_photo(
    message: Message,
    state: FSMContext,
):
    file_id = message.photo[-1].file_id
    await state.update_data(avatar_file_id=file_id)
    await _ask_role(message, state)


@router.callback_query(RegistrationStates.avatar, F.data == "avatar_from_tg")
async def process_avatar_from_tg(
    callback: CallbackQuery,
    state: FSMContext,
    bot: Bot,
):
    photos = await bot.get_user_profile_photos(
        callback.from_user.id,
        limit=1,
    )
    if photos.total_count > 0 and photos.photos:
        file_id = photos.photos[0][-1].file_id
        await state.update_data(avatar_file_id=file_id)

    await _ask_role(callback.message, state)
    await callback.answer()


@router.callback_query(RegistrationStates.avatar, F.data == "avatar_skip")
async def process_avatar_skip(
    callback: CallbackQuery,
    state: FSMContext,
):
    await _ask_role(callback.message, state)
    await callback.answer()


async def _ask_role(message: Message, state: FSMContext):
    await state.set_state(RegistrationStates.role)
    data = await state.get_data()
    is_edit = data.get("is_edit", False)

    kb = InlineKeyboardBuilder()
    for text, code in ROLE_OPTIONS:
        kb.button(text=text, callback_data=f"role:{code}")
    if is_edit:
        kb.button(text="Отменить редактирование", callback_data=PROFILE_CANCEL_CB)
    kb.adjust(2)

    await message.answer(
        "Шаг 3 из 7.\nВыбери свою роль в IT:",
        reply_markup=kb.as_markup(),
    )


# ===== Шаг 3: роль =====


@router.callback_query(RegistrationStates.role, F.data.startswith("role:"))
async def process_role(
    callback: CallbackQuery,
    state: FSMContext,
):
    _, role_code = callback.data.split(":", 1)
    await state.update_data(role=role_code)

    await state.set_state(RegistrationStates.stack)

    data = await state.get_data()
    is_edit = data.get("is_edit", False)

    stack_options = STACK_OPTIONS.get(role_code, [])
    kb = InlineKeyboardBuilder()
    if stack_options:
        for text, code in stack_options:
            kb.button(text=text, callback_data=f"stack:{code}")
        text = "Шаг 4 из 7.\nВыбери стэк, который тебе ближе."
    else:
        for text, code in [
            ("Python", "python"),
            ("Golang", "golang"),
            ("JavaScript", "js"),
        ]:
            kb.button(text=text, callback_data=f"stack:{code}")
        text = "Шаг 4 из 7.\nВыбери основной стэк."

    if is_edit:
        kb.button(text="Отменить редактирование", callback_data=PROFILE_CANCEL_CB)
    kb.adjust(2)

    await callback.message.edit_text(
        text,
        reply_markup=kb.as_markup(),
    )
    await callback.answer()


# ===== Шаг 4: стек =====


@router.callback_query(RegistrationStates.stack, F.data.startswith("stack:"))
async def process_stack(
    callback: CallbackQuery,
    state: FSMContext,
):
    _, stack_code = callback.data.split(":", 1)
    await state.update_data(stack=stack_code)

    data = await state.get_data()
    role = data.get("role")
    # fullstack: мультивыбор фреймворков
    if role == "fullstack":
        await state.update_data(
            framework_mode="multi",
            frameworks_selected=[],
            framework_custom=None,
        )
        await _ask_frameworks_fullstack(callback.message, state, stack_code)
    else:
        # обычный режим: один фреймворк
        await state.update_data(framework_mode="single")
        await state.set_state(RegistrationStates.framework)

        fw_options = FRAMEWORK_OPTIONS.get(stack_code, [])
        kb = InlineKeyboardBuilder()
        if fw_options:
            for text, code in fw_options:
                kb.button(text=text, callback_data=f"framework:{code}")
        kb.button(text="Другое", callback_data="framework:other")

        is_edit = data.get("is_edit", False)
        if is_edit:
            kb.button(text="Отменить редактирование", callback_data=PROFILE_CANCEL_CB)

        kb.adjust(2)

        await callback.message.edit_text(
            "Шаг 5 из 7.\n"
            "Выбери основной фреймворк. Если нужного нет — выбери «Другое» и впиши свой.",
            reply_markup=kb.as_markup(),
        )

    await callback.answer()


async def _ask_frameworks_fullstack(
    message: Message,
    state: FSMContext,
    stack_code: str,
):
    await state.set_state(RegistrationStates.framework)
    data = await state.get_data()
    selected = data.get("frameworks_selected", []) or []
    is_edit = data.get("is_edit", False)

    kb = _build_frameworks_keyboard_fullstack(stack_code, selected, is_edit)

    await message.edit_text(
        "Шаг 5 из 7.\n"
        "Выбери один или несколько фреймворков, с которыми ты работаешь.\n"
        "Можно выбирать несколько. Если нужного нет — «Другое». "
        "Когда закончишь — нажми «Готово».",
        reply_markup=kb.as_markup(),
    )


# ===== Шаг 5: фреймворк =====


@router.callback_query(RegistrationStates.framework, F.data.startswith("framework:"))
async def process_framework_callback(
    callback: CallbackQuery,
    state: FSMContext,
):
    _, fw_code = callback.data.split(":", 1)
    data = await state.get_data()
    mode = data.get("framework_mode", "single")
    stack_code = data.get("stack")
    is_edit = data.get("is_edit", False)

    # На всякий, если вдруг сюда попали в multi — игнорим
    if mode == "multi":
        await callback.answer()
        return

    if fw_code == "other":
        markup = None
        if is_edit:
            kb = InlineKeyboardBuilder()
            kb.button(text="Отменить редактирование", callback_data=PROFILE_CANCEL_CB)
            markup = kb.as_markup()

        await callback.message.edit_text(
            "Напиши свой фреймворк или стек текстом (например: FastAPI, "
            "Django REST, Express, Next.js и т.п.).",
            reply_markup=markup,
        )
        await callback.answer()
        return

    # Обычный режим: один фреймворк
    fw_options = FRAMEWORK_OPTIONS.get(stack_code, [])
    label_map = {code: text for (text, code) in fw_options}
    label = label_map.get(fw_code, fw_code)

    await state.update_data(framework=label)
    await state.update_data(skills_selected=[], skills_custom=None)

    # Переход к навыкам
    await _ask_skills(callback.message, state)
    await callback.answer()


@router.callback_query(
    RegistrationStates.framework, F.data.startswith("framework_multi:")
)
async def process_framework_multi_callback(
    callback: CallbackQuery,
    state: FSMContext,
):
    _, fw_code = callback.data.split(":", 1)
    data = await state.get_data()
    stack_code = data.get("stack")
    selected: list[str] = data.get("frameworks_selected", []) or []
    is_edit = data.get("is_edit", False)

    if fw_code == "done":
        # финализируем выбор
        fw_options = FRAMEWORK_OPTIONS.get(stack_code, [])
        label_map = {code: text for (text, code) in fw_options}
        labels = [label_map.get(c, c) for c in selected]
        custom = data.get("framework_custom")

        parts: list[str] = []
        if labels:
            parts.append(", ".join(labels))
        if custom:
            parts.append(custom)

        framework_str = "; ".join(parts) if parts else None
        await state.update_data(framework=framework_str)
        await state.update_data(frameworks_selected=None, framework_custom=None)

        # идём к навыкам
        await state.update_data(skills_selected=[], skills_custom=None)
        await _ask_skills(callback.message, state)
        await callback.answer()
        return

    if fw_code == "other":
        # ввод произвольных фреймворков текстом
        markup = None
        if is_edit:
            kb = InlineKeyboardBuilder()
            kb.button(text="Отменить редактирование", callback_data=PROFILE_CANCEL_CB)
            markup = kb.as_markup()

        await callback.message.edit_text(
            "Напиши свои фреймворки текстом через запятую.\n"
            "Например: Django, FastAPI, React, Next.js.",
            reply_markup=markup,
        )
        await state.set_state(RegistrationStates.framework)
        await state.update_data(framework_mode="multi_text")
        await callback.answer()
        return

    # toggle выбор
    if fw_code in selected:
        selected.remove(fw_code)
    else:
        selected.append(fw_code)

    await state.update_data(frameworks_selected=selected)

    kb = _build_frameworks_keyboard_fullstack(stack_code, selected, is_edit)
    await callback.message.edit_text(
        "Шаг 5 из 7.\n"
        "Выбери один или несколько фреймворков. "
        "Если всё выбрал — нажми «Готово». Если чего-то нет — «Другое».",
        reply_markup=kb.as_markup(),
    )
    await callback.answer()


@router.message(RegistrationStates.framework, F.text)
async def process_framework_text(
    message: Message,
    state: FSMContext,
):
    data = await state.get_data()
    mode = data.get("framework_mode", "single")

    # если это multi_text (fullstack + "Другое")
    if mode == "multi_text":
        await state.update_data(framework_custom=message.text.strip())
        await state.update_data(framework_mode="multi")
        stack_code = data.get("stack")
        await _ask_frameworks_fullstack(message, state, stack_code)
        return

    # обычный режим: просто один фреймворк строкой
    await state.update_data(framework=message.text.strip())
    await state.update_data(skills_selected=[], skills_custom=None)
    await _ask_skills(message, state)


# ===== Шаг 6: навыки (инлайн + "Другое") =====


async def _ask_skills(message: Message, state: FSMContext):
    data = await state.get_data()
    selected = data.get("skills_selected", []) or []
    is_edit = data.get("is_edit", False)

    kb = _build_skills_keyboard(selected, is_edit)

    await state.set_state(RegistrationStates.skills)

    await message.answer(
        "Шаг 6 из 7.\n"
        "Выбери свои общие навыки. Можно выбрать несколько: нажимай на кнопки, "
        "чтобы включать/выключать. Если нужного нет — нажми «Другое» и впиши. "
        "Когда закончишь — нажми «Готово».",
        reply_markup=kb.as_markup(),
    )


@router.callback_query(RegistrationStates.skills, F.data.startswith("skill:"))
async def process_skill_callback(
    callback: CallbackQuery,
    state: FSMContext,
):
    _, code = callback.data.split(":", 1)
    data = await state.get_data()
    selected: list[str] = data.get("skills_selected", []) or []
    is_edit = data.get("is_edit", False)

    if code == "done":
        # финализируем выбор
        label_map = {c: l for (l, c) in SKILL_OPTIONS if c not in ("other", "done")}
        selected_labels = [label_map[c] for c in selected if c in label_map]
        custom = data.get("skills_custom")

        parts: list[str] = []
        if selected_labels:
            parts.append(", ".join(selected_labels))
        if custom:
            parts.append(custom)

        skills_str = "; ".join(parts) if parts else None
        await state.update_data(skills=skills_str)

        # переходим к целям
        await state.set_state(RegistrationStates.goals)

        kb = InlineKeyboardBuilder()
        for text, g_code in GOAL_OPTIONS:
            kb.button(text=text, callback_data=f"goal:{g_code}")
        if is_edit:
            kb.button(text="Отменить редактирование", callback_data=PROFILE_CANCEL_CB)
        kb.adjust(1)

        await callback.message.edit_text(
            "Шаг 7 из 7.\nВыбери свою основную цель в LinkIT:",
            reply_markup=kb.as_markup(),
        )
        await callback.answer()
        return

    if code == "other":
        await state.set_state(RegistrationStates.skills_custom)

        markup = None
        if is_edit:
            kb = InlineKeyboardBuilder()
            kb.button(text="Отменить редактирование", callback_data=PROFILE_CANCEL_CB)
            markup = kb.as_markup()

        await callback.message.edit_text(
            "Напиши свои навыки текстом через запятую.\n"
            "Например: Git, SQL, Docker, Linux, английский B1.",
            reply_markup=markup,
        )
        await callback.answer()
        return

    # toggle навыка
    if code in selected:
        selected.remove(code)
    else:
        selected.append(code)

    await state.update_data(skills_selected=selected)

    kb = _build_skills_keyboard(selected, is_edit)
    await callback.message.edit_text(
        "Шаг 6 из 7.\n"
        "Выбери свои общие навыки. Можно выбрать несколько. "
        "Если всё выбрал — нажми «Готово». Если чего-то нет — «Другое».",
        reply_markup=kb.as_markup(),
    )
    await callback.answer()


@router.message(RegistrationStates.skills_custom, F.text)
async def process_skills_custom(
    message: Message,
    state: FSMContext,
):
    await state.update_data(skills_custom=message.text.strip())
    # возвращаемся к выбору навыков
    await _ask_skills(message, state)


# ===== Шаг 7: цели =====


@router.callback_query(RegistrationStates.goals, F.data.startswith("goal:"))
async def process_goal(
    callback: CallbackQuery,
    state: FSMContext,
):
    _, goal_code = callback.data.split(":", 1)
    await state.update_data(goals=goal_code)

    await state.set_state(RegistrationStates.about)

    data = await state.get_data()
    is_edit = data.get("is_edit", False)

    markup = None
    if is_edit:
        kb = InlineKeyboardBuilder()
        kb.button(text="Отменить редактирование", callback_data=PROFILE_CANCEL_CB)
        markup = kb.as_markup()

    await callback.message.edit_text(
        "Финальный шаг.\n"
        "Кратко напиши о себе: кто ты, чем занимаешься и чего ждёшь от напарника/ментора/проекта.",
        reply_markup=markup,
    )
    await callback.answer()


# ===== Финал: о себе, сохранение =====


@router.message(RegistrationStates.about, F.text)
async def process_about(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
):
    await state.update_data(about=message.text.strip())
    data = await state.get_data()
    await state.clear()

    name = data.get("name")
    avatar_file_id = data.get("avatar_file_id")
    role = data.get("role")
    stack = data.get("stack")
    framework = data.get("framework")
    skills = data.get("skills")
    goals = data.get("goals")
    about = data.get("about")

    profile = await update_profile_data(
        session,
        telegram_id=message.from_user.id,
        first_name=name,
        avatar_file_id=avatar_file_id,
        role=role,
        stack=stack,
        framework=framework,
        skills=skills,
        goals=goals,
        about=about,
    )

    if not profile:
        await message.answer(
            "Не удалось сохранить профиль. Попробуй позже или заново через /edit_profile."
        )
        return

    kb = ReplyKeyboardBuilder()
    kb.button(text="👥 Лента разработчиков")
    kb.button(text="🚀 Лента проектов")
    kb.button(text="🆕 Новый проект")
    kb.button(text="👤 Профиль")
    kb.adjust(2, 2)

    await message.answer(
        "Профиль сохранён.\n\n"
        "В будущем можно будет привязать GitHub и GitLab, чтобы подтягивать репозитории "
        "и активность прямо в профиль.\n\n"
        "Что дальше?",
        reply_markup=kb.as_markup(resize_keyboard=True),
    )


# ===== Кнопки под профилем =====


@router.callback_query(F.data == "profile_rewards")
async def on_profile_rewards(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer(
        "Раздел с наградами пока в разработке. Скоро здесь будут ваши достижения."
    )


@router.callback_query(F.data == "profile_edit")
async def on_profile_edit(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await _start_profile_flow(callback.message, state, allow_cancel=True)


@router.callback_query(F.data == PROFILE_CANCEL_CB)
async def on_profile_cancel_edit(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
):
    """
    Отмена редактирования профиля:
    - чистим FSM,
    - ничего не сохраняем,
    - показываем текущий профиль как он есть в БД.
    """
    await state.clear()

    # пробуем удалить сообщение с "шагом"
    try:
        await callback.message.delete()
    except Exception:
        pass

    profile = await get_profile(session, callback.from_user.id)

    if not profile:
        await callback.answer("Редактирование отменено.", show_alert=False)
        await callback.message.answer(
            "Редактирование отменено.\n"
            "Пока у тебя ещё нет сохранённого профиля. "
            "Можешь начать заново через /edit_profile."
        )
        return

    text = format_profile_text(
        profile,
        fallback_username=callback.from_user.username,
    )

    kb = InlineKeyboardBuilder()
    kb.button(text="🏆 Награды", callback_data="profile_rewards")
    kb.button(text="✏️ Редактировать", callback_data="profile_edit")
    kb.adjust(2)

    # показываем актуальный профиль
    if profile.avatar_file_id:
        await bot.send_photo(
            chat_id=callback.message.chat.id,
            photo=profile.avatar_file_id,
            caption=text,
            reply_markup=kb.as_markup(),
        )
    else:
        await callback.message.answer(
            text,
            reply_markup=kb.as_markup(),
        )

    await callback.answer(
        "Редактирование отменено, профиль не изменён.", show_alert=False
    )
