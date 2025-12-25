import logging
from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from services import search_profiles_for_user
from views import format_profile_public
from models import Profile
from constants import ROLE_OPTIONS, STACK_OPTIONS, STACK_LABELS, GOAL_OPTIONS

router = Router()
logger = logging.getLogger(__name__)


# ===== хелперы для ленты =====


async def send_dev_profile_card(
    *,
    source_message: Message,
    profile: Profile,
    bot: Bot,
):
    """
    Отправляем карточку профиля:
    - фотка (если есть),
    - анонимное описание (без username),
    - инлайн-клавиатура:
        1) Награды
        2) Откликнуться
        3) Предыдущий / Следующий
    """
    text = format_profile_public(profile)

    logger.info(
        "devfeed_filters_profile_card_sent user_id=%s target_id=%s has_avatar=%s",
        source_message.from_user.id if source_message.from_user else None,
        profile.telegram_id,
        bool(getattr(profile, "avatar_file_id", None)),
    )

    kb = InlineKeyboardBuilder()
    kb.button(
        text="🏆 Награды пользователя",
        callback_data=f"devfeed_rewards:{profile.telegram_id}",
    )
    kb.button(
        text="🤝 Откликнуться",
        callback_data=f"devfeed_request:{profile.telegram_id}",
    )
    kb.button(
        text="⬅️ Предыдущий",
        callback_data="devfeed_prev",
    )
    kb.button(
        text="➡️ Следующий",
        callback_data="devfeed_next",
    )
    kb.adjust(1, 1, 2)

    if getattr(profile, "avatar_file_id", None):
        await bot.send_photo(
            chat_id=source_message.chat.id,
            photo=profile.avatar_file_id,
            caption=text,
            reply_markup=kb.as_markup(),
        )
    else:
        await source_message.answer(
            text,
            reply_markup=kb.as_markup(),
        )


def _code_to_label(code: str | None, options: list[tuple[str, str]]) -> str | None:
    if not code:
        return None
    for label, c in options:
        if c == code:
            return label
    return code


def build_filters_summary(filters: dict | None) -> str:
    if not filters:
        return "Фильтры: не выбраны — показываю всех подходящих разработчиков."

    role_code = filters.get("role")
    stack_code = filters.get("stack")
    goal_code = filters.get("goal")

    parts: list[str] = []

    if role_code:
        role_label = _code_to_label(role_code, ROLE_OPTIONS)
        parts.append(f"Роль: {role_label}")

    if stack_code:
        stack_label = STACK_LABELS.get(stack_code, stack_code)
        parts.append(f"Стек: {stack_label}")

    if goal_code:
        goal_label = _code_to_label(goal_code, GOAL_OPTIONS)
        parts.append(f"Цель: {goal_label}")

    if not parts:
        return "Фильтры: не выбраны — показываю всех подходящих разработчиков."

    return "Фильтры: " + ", ".join(parts)


async def _render_filters_menu(
    *,
    state: FSMContext,
    bot: Bot,
    message: Message | None = None,
):
    """
    Если message передан — отправляем новое меню и запоминаем message_id.
    Если нет — редактируем существующее сообщение с меню.
    """
    data = await state.get_data()
    filters: dict = data.get("devfeed_filters", {}) or {}

    summary = build_filters_summary(filters)
    text = (
        "Как будем искать? Можешь выбрать пару фильтров, а можно сразу смотреть ленту.\n\n"
        f"{summary}"
    )

    kb = InlineKeyboardBuilder()
    kb.button(text="🎭 Роль", callback_data="devf_filter_role")
    kb.button(text="🎯 Цель", callback_data="devf_filter_goal")
    kb.button(text="🧩 Стек", callback_data="devf_filter_stack")
    kb.button(text="⚙️ Сбросить фильтры", callback_data="devf_filter_reset")
    kb.button(text="🔍 Показать ленту", callback_data="devf_filter_show")
    kb.adjust(2, 2, 1)

    if message is not None:
        logger.info(
            "devfeed_filters_menu_show_first user_id=%s filters=%s",
            message.from_user.id if message.from_user else None,
            filters,
        )
        # первый запуск из "👥 Лента разработчиков"
        sent = await message.answer(text, reply_markup=kb.as_markup())
        await state.update_data(
            devfeed_filters_msg_id=sent.message_id,
            devfeed_filters_chat_id=sent.chat.id,
        )
    else:
        chat_id = data.get("devfeed_filters_chat_id")
        msg_id = data.get("devfeed_filters_msg_id")
        if not chat_id or not msg_id:
            logger.debug(
                "devfeed_filters_menu_update_missing_message chat_id=%s msg_id=%s filters=%s",
                chat_id,
                msg_id,
                filters,
            )
            # если по какой-то причине нет сохранённого сообщения — ничего не делаем
            return
        try:
            logger.info(
                "devfeed_filters_menu_update chat_id=%s msg_id=%s filters=%s",
                chat_id,
                msg_id,
                filters,
            )
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=msg_id,
                text=text,
                reply_markup=kb.as_markup(),
            )
        except Exception:
            # сообщение могли удалить — не критичная ошибка
            logger.debug(
                "devfeed_filters_menu_update_failed chat_id=%s msg_id=%s",
                chat_id,
                msg_id,
                exc_info=True,
            )


def _filter_profile_by_stack_and_nonempty(
    profile: Profile,
    stack_code: str | None,
) -> bool:
    # скрываем полностью пустые профили
    important_fields = [
        profile.first_name,
        profile.role,
        profile.stack,
        profile.framework,
        profile.skills,
        profile.goals,
        profile.about,
    ]
    if not any(
        (value is not None) and str(value).strip() for value in important_fields
    ):
        return False

    # фильтр по стеку (строго по коду)
    if stack_code:
        if not profile.stack:
            return False
        if profile.stack != stack_code:
            return False

    return True


# ===== вход в фильтры по "👥 Лента разработчиков" =====


@router.message(F.text == "👥 Лента разработчиков")
async def devfeed_filters_entry(
    message: Message,
    state: FSMContext,
    bot: Bot,
):
    logger.info(
        "devfeed_filters_entry user_id=%s",
        message.from_user.id if message.from_user else None,
    )
    # не сбрасываем фильтры — пользователь может возвращаться и докручивать
    await _render_filters_menu(state=state, bot=bot, message=message)


# ===== кнопки фильтров =====


@router.callback_query(F.data == "devf_filter_reset")
async def devf_filter_reset(
    callback: CallbackQuery,
    state: FSMContext,
    bot: Bot,
):
    logger.info(
        "devfeed_filters_reset user_id=%s",
        callback.from_user.id,
    )
    await callback.answer("Фильтры сброшены", show_alert=False)
    await state.update_data(devfeed_filters={})
    await _render_filters_menu(state=state, bot=bot)


@router.callback_query(F.data == "devf_filter_role")
async def devf_filter_role(
    callback: CallbackQuery,
    state: FSMContext,
):
    logger.info(
        "devfeed_filters_role_open user_id=%s",
        callback.from_user.id,
    )
    await callback.answer()
    kb = InlineKeyboardBuilder()
    for label, code in ROLE_OPTIONS:
        kb.button(text=label, callback_data=f"devf_set_role:{code}")
    kb.button(text="❌ Не выбирать", callback_data="devf_cancel_submenu")
    kb.adjust(2)

    await callback.message.answer(
        "Выбери роль, по которой будем фильтровать ленту:",
        reply_markup=kb.as_markup(),
    )


@router.callback_query(F.data.startswith("devf_set_role:"))
async def devf_set_role(
    callback: CallbackQuery,
    state: FSMContext,
    bot: Bot,
):
    _, role_code = callback.data.split(":", 1)

    logger.info(
        "devfeed_filters_role_set user_id=%s role_code=%s",
        callback.from_user.id,
        role_code,
    )

    data = await state.get_data()
    filters: dict = data.get("devfeed_filters", {}) or {}

    # при смене роли сбрасываем стек, чтобы не висел чужой
    filters["role"] = role_code
    filters.pop("stack", None)

    await state.update_data(devfeed_filters=filters)

    # обновляем главное меню
    await _render_filters_menu(state=state, bot=bot)

    # удаляем сообщение с выбором роли
    try:
        await callback.message.delete()
    except Exception:
        logger.debug(
            "devfeed_filters_role_msg_delete_failed user_id=%s",
            callback.from_user.id,
            exc_info=True,
        )

    await callback.answer("Роль выбрана", show_alert=False)


@router.callback_query(F.data == "devf_filter_goal")
async def devf_filter_goal(
    callback: CallbackQuery,
    state: FSMContext,
):
    logger.info(
        "devfeed_filters_goal_open user_id=%s",
        callback.from_user.id,
    )
    await callback.answer()
    kb = InlineKeyboardBuilder()
    for label, code in GOAL_OPTIONS:
        kb.button(text=label, callback_data=f"devf_set_goal:{code}")
    kb.button(text="❌ Не выбирать", callback_data="devf_cancel_submenu")
    kb.adjust(1)

    await callback.message.answer(
        "Выбери цель, с которой будем подбирать разработчиков:",
        reply_markup=kb.as_markup(),
    )


@router.callback_query(F.data.startswith("devf_set_goal:"))
async def devf_set_goal(
    callback: CallbackQuery,
    state: FSMContext,
    bot: Bot,
):
    _, goal_code = callback.data.split(":", 1)

    logger.info(
        "devfeed_filters_goal_set user_id=%s goal_code=%s",
        callback.from_user.id,
        goal_code,
    )

    data = await state.get_data()
    filters: dict = data.get("devfeed_filters", {}) or {}

    filters["goal"] = goal_code
    await state.update_data(devfeed_filters=filters)

    await _render_filters_menu(state=state, bot=bot)

    try:
        await callback.message.delete()
    except Exception:
        logger.debug(
            "devfeed_filters_goal_msg_delete_failed user_id=%s",
            callback.from_user.id,
            exc_info=True,
        )

    await callback.answer("Цель выбрана", show_alert=False)


@router.callback_query(F.data == "devf_filter_stack")
async def devf_filter_stack(
    callback: CallbackQuery,
    state: FSMContext,
):
    data = await state.get_data()
    filters: dict = data.get("devfeed_filters", {}) or {}
    role_code = filters.get("role")

    logger.info(
        "devfeed_filters_stack_open user_id=%s role_code=%s",
        callback.from_user.id,
        role_code,
    )

    if not role_code:
        await callback.answer("Сначала выбери роль 👆", show_alert=True)
        return

    stack_options = STACK_OPTIONS.get(role_code, [])
    if not stack_options:
        await callback.answer(
            "Для этой роли пока нет преднастроенного стека.", show_alert=True
        )
        return

    kb = InlineKeyboardBuilder()
    for label, code in stack_options:
        kb.button(text=label, callback_data=f"devf_set_stack:{code}")
    kb.button(text="🧹 Сбросить стек", callback_data="devf_clear_stack")
    kb.button(text="❌ Закрыть", callback_data="devf_cancel_submenu")
    kb.adjust(2)

    await callback.answer()
    await callback.message.answer(
        "Выбери стек для фильтрации ленты:",
        reply_markup=kb.as_markup(),
    )


@router.callback_query(F.data.startswith("devf_set_stack:"))
async def devf_set_stack(
    callback: CallbackQuery,
    state: FSMContext,
    bot: Bot,
):
    _, stack_code = callback.data.split(":", 1)

    logger.info(
        "devfeed_filters_stack_set user_id=%s stack_code=%s",
        callback.from_user.id,
        stack_code,
    )

    data = await state.get_data()
    filters: dict = data.get("devfeed_filters", {}) or {}

    filters["stack"] = stack_code
    await state.update_data(devfeed_filters=filters)

    await _render_filters_menu(state=state, bot=bot)

    try:
        await callback.message.delete()
    except Exception:
        logger.debug(
            "devfeed_filters_stack_msg_delete_failed user_id=%s",
            callback.from_user.id,
            exc_info=True,
        )

    await callback.answer("Стек выбран", show_alert=False)


@router.callback_query(F.data == "devf_clear_stack")
async def devf_clear_stack(
    callback: CallbackQuery,
    state: FSMContext,
    bot: Bot,
):
    logger.info(
        "devfeed_filters_stack_clear user_id=%s",
        callback.from_user.id,
    )

    data = await state.get_data()
    filters: dict = data.get("devfeed_filters", {}) or {}

    filters.pop("stack", None)
    await state.update_data(devfeed_filters=filters)

    await _render_filters_menu(state=state, bot=bot)

    try:
        await callback.message.delete()
    except Exception:
        logger.debug(
            "devfeed_filters_stack_clear_msg_delete_failed user_id=%s",
            callback.from_user.id,
            exc_info=True,
        )

    await callback.answer("Стек сброшен", show_alert=False)


@router.callback_query(F.data == "devf_cancel_submenu")
async def devf_cancel_submenu(callback: CallbackQuery):
    logger.info(
        "devfeed_filters_submenu_cancel user_id=%s",
        callback.from_user.id,
    )
    # просто удаляем окно с выбором
    try:
        await callback.message.delete()
    except Exception:
        logger.debug(
            "devfeed_filters_submenu_delete_failed user_id=%s",
            callback.from_user.id,
            exc_info=True,
        )
    await callback.answer()


# ===== запуск ленты с учётом фильтров =====


@router.callback_query(F.data == "devf_filter_show")
async def devf_filter_show(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
):
    await callback.answer()

    data = await state.get_data()
    filters: dict = data.get("devfeed_filters", {}) or {}

    role_code = filters.get("role")
    goal_code = filters.get("goal")
    stack_code = filters.get("stack")

    logger.info(
        "devfeed_filters_show user_id=%s filters=%s",
        callback.from_user.id,
        filters,
    )

    # достаём кандидатов по роли/цели из БД
    profiles = await search_profiles_for_user(
        session,
        requester_id=callback.from_user.id,
        goal=goal_code,
        role=role_code,
        limit=100,
    )

    raw_count = len(profiles)

    # доп. фильтрация: стек + выкинуть пустые профили
    profiles = [
        p for p in profiles if _filter_profile_by_stack_and_nonempty(p, stack_code)
    ]

    filtered_count = len(profiles)

    # на всякий случай — убираем самого себя
    profiles = [p for p in profiles if p.telegram_id != callback.from_user.id]

    final_count = len(profiles)

    logger.info(
        "devfeed_filters_result user_id=%s raw=%s after_stack=%s final=%s",
        callback.from_user.id,
        raw_count,
        filtered_count,
        final_count,
    )

    if not profiles:
        await callback.message.answer(
            "По таким фильтрам пока никого не нашлось.\n"
            "Попробуй изменить фильтры или сбросить их.",
        )
        return

    # сохраняем в FSM список id для devfeed_next/devfeed_prev
    await state.update_data(
        devfeed_profile_ids=[p.telegram_id for p in profiles],
        devfeed_index=0,
    )

    # сообщение с фильтрами — уже есть и будет обновляться через _render_filters_menu
    summary = build_filters_summary(filters)
    await callback.message.answer(summary)

    # показываем первую карточку
    await send_dev_profile_card(
        source_message=callback.message,
        profile=profiles[0],
        bot=bot,
    )
