import logging

from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from services import (
    get_profile,
    send_connection_request,
)
from views import format_profile_public, html_safe


router = Router()
logger = logging.getLogger(__name__)


class DevfeedRequestStates(StatesGroup):
    waiting_greeting = State()


# ===== вспомогалки для навигации =====


async def _send_dev_profile_card(
    *,
    source_message: Message,
    profile,
    bot: Bot,
):
    """
    Отправляем карточку профиля:
    - фотка (если есть),
    - описание,
    - инлайн-клавиатура:
        1) Награды
        2) Откликнуться
        3) Предыдущий / Следующий
    """
    text = format_profile_public(profile)

    logger.info(
        "devfeed_profile_card_sent user_id=%s target_id=%s has_avatar=%s",
        source_message.from_user.id if source_message.from_user else None,
        getattr(profile, "telegram_id", None),
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
    kb.button(text="⬅️ Предыдущий", callback_data="devfeed_prev")
    kb.button(text="➡️ Следующий", callback_data="devfeed_next")
    kb.adjust(1, 1, 2)

    if getattr(profile, "avatar_file_id", None):
        await bot.send_photo(
            chat_id=source_message.chat.id,
            photo=profile.avatar_file_id,
            caption=text,
            reply_markup=kb.as_markup(),
        )
    else:
        await source_message.answer(text, reply_markup=kb.as_markup())


async def _get_devfeed_profile_at_index(
    *,
    state: FSMContext,
    session: AsyncSession,
    requester_id: int,
    new_index: int,
):
    """
    Берём профиль по конкретному индексу из сохранённого списка.
    """
    data = await state.get_data()
    ids: list[int] | None = data.get("devfeed_profile_ids")

    if not ids:
        logger.info("devfeed_empty_ids requester_id=%s", requester_id)
        return None, None

    if new_index < 0 or new_index >= len(ids):
        logger.info(
            "devfeed_index_out_of_range requester_id=%s new_index=%s total=%s",
            requester_id,
            new_index,
            len(ids),
        )
        return None, None

    next_tg_id = ids[new_index]
    profile = await get_profile(session, next_tg_id)

    # пропускаем самого себя на всякий
    if profile and profile.telegram_id == requester_id:
        logger.info(
            "devfeed_skip_self requester_id=%s index=%s", requester_id, new_index
        )
        if new_index + 1 < len(ids):
            return await _get_devfeed_profile_at_index(
                state=state,
                session=session,
                requester_id=requester_id,
                new_index=new_index + 1,
            )
        return None, None

    await state.update_data(devfeed_index=new_index)

    logger.info(
        "devfeed_profile_selected requester_id=%s target_id=%s index=%s",
        requester_id,
        next_tg_id,
        new_index,
    )

    return profile, new_index


@router.callback_query(F.data == "devfeed_next")
async def devfeed_next_callback(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
):
    data = await state.get_data()
    index: int | None = data.get("devfeed_index", 0)
    index = index or 0
    new_index = index + 1

    logger.info(
        "devfeed_next_clicked user_id=%s current_index=%s new_index=%s",
        callback.from_user.id,
        index,
        new_index,
    )

    profile, _ = await _get_devfeed_profile_at_index(
        state=state,
        session=session,
        requester_id=callback.from_user.id,
        new_index=new_index,
    )

    if not profile:
        await callback.answer("Это была последняя карточка", show_alert=False)
        await callback.message.answer(
            "Ты посмотрел всех доступных разработчиков в ленте.\n"
            "Загляни позже — появятся новые."
        )
        return

    await callback.answer()

    await _send_dev_profile_card(
        source_message=callback.message,
        profile=profile,
        bot=bot,
    )

    try:
        await callback.message.delete()
    except Exception:
        logger.debug(
            "devfeed_next_message_delete_failed user_id=%s",
            callback.from_user.id,
            exc_info=True,
        )


@router.callback_query(F.data == "devfeed_prev")
async def devfeed_prev_callback(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
):
    data = await state.get_data()
    index: int | None = data.get("devfeed_index", 0)
    index = index or 0
    new_index = index - 1

    logger.info(
        "devfeed_prev_clicked user_id=%s current_index=%s new_index=%s",
        callback.from_user.id,
        index,
        new_index,
    )

    if new_index < 0:
        await callback.answer("Это первая карточка", show_alert=False)
        return

    profile, _ = await _get_devfeed_profile_at_index(
        state=state,
        session=session,
        requester_id=callback.from_user.id,
        new_index=new_index,
    )

    if not profile:
        await callback.answer("Это первая карточка", show_alert=False)
        return

    await callback.answer()

    await _send_dev_profile_card(
        source_message=callback.message,
        profile=profile,
        bot=bot,
    )

    try:
        await callback.message.delete()
    except Exception:
        logger.debug(
            "devfeed_prev_message_delete_failed user_id=%s",
            callback.from_user.id,
            exc_info=True,
        )


# ===== кнопка "🏆 Награды пользователя" =====


@router.callback_query(F.data.startswith("devfeed_rewards:"))
async def devfeed_rewards_callback(callback: CallbackQuery):
    logger.info(
        "devfeed_rewards_opened user_id=%s data=%s",
        callback.from_user.id,
        callback.data,
    )
    await callback.answer()
    await callback.message.answer(
        "Раздел с наградами пока в разработке.\n"
        "В будущем здесь будут ачивки за менторство, участие в проектах и активность.",
    )


# ===== Вспомогалка: отправка заявки =====


async def _process_connection_request(
    *,
    session: AsyncSession,
    bot: Bot,
    from_id: int,
    target_tg_id: int,
    source_message: Message,
    greeting: str | None = None,
):
    logger.info(
        "connection_request_attempt from_id=%s to_id=%s has_greeting=%s",
        from_id,
        target_tg_id,
        bool(greeting),
    )

    req, reason = await send_connection_request(
        session,
        from_id=from_id,
        to_id=target_tg_id,
    )

    if reason == "self":
        await source_message.answer("Это ты сам 😄")
        return

    if reason == "exists":
        await source_message.answer("Заявка уже отправлена, ждём ответа.")
        return

    if reason == "limit":
        await source_message.answer(
            "Ты достиг лимита заявок на сегодня.\n\n"
            f"Сейчас лимит — {settings.max_connection_requests_per_day}, "
            "завтра счётчик обнулится 🙂",
        )
        return

    # ok
    sender_profile = await get_profile(session, from_id)
    sender_text = format_profile_public(sender_profile)  # без username

    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Принять", callback_data=f"conn_accept:{req.id}")
    kb.button(text="❌ Отклонить", callback_data=f"conn_reject:{req.id}")
    kb.adjust(2)

    safe_greeting = html_safe(greeting, default="—") if greeting else None

    if safe_greeting:
        notify_text = (
            "Тебе пришла заявка на сотрудничество в Link IT.\n\n"
            "Профиль отправителя:\n\n"
            f"{sender_text}\n\n"
            "Сообщение от отправителя:\n"
            f"{safe_greeting}\n\n"
            "Контакты откроются, если ты примешь заявку."
        )
    else:
        notify_text = (
            "Тебе пришла заявка на сотрудничество в Link IT.\n\n"
            "Профиль отправителя:\n\n"
            f"{sender_text}\n\n"
            "Контакты откроются, если ты примешь заявку."
        )

    try:
        if sender_profile and getattr(sender_profile, "avatar_file_id", None):
            await bot.send_photo(
                chat_id=target_tg_id,
                photo=sender_profile.avatar_file_id,
                caption=notify_text,
                reply_markup=kb.as_markup(),
            )
        else:
            await bot.send_message(
                chat_id=target_tg_id,
                text=notify_text + "\n\n(У отправителя пока нет аватарки в профиле)",
                reply_markup=kb.as_markup(),
            )
        logger.info(
            "connection_request_notification_sent from_id=%s to_id=%s request_id=%s",
            from_id,
            target_tg_id,
            getattr(req, "id", None),
        )
    except Exception:
        logger.debug(
            "connection_request_notification_failed from_id=%s to_id=%s request_id=%s",
            from_id,
            target_tg_id,
            getattr(req, "id", None),
            exc_info=True,
        )

    await source_message.answer(
        "Заявка отправлена.\n\n"
        "Когда пользователь ответит, я пришлю тебе уведомление: "
        "либо контакты, либо отказ."
    )

    logger.info(
        "connection_request_created from_id=%s to_id=%s request_id=%s",
        from_id,
        target_tg_id,
        getattr(req, "id", None),
    )


# ===== кнопка "🤝 Откликнуться" =====


@router.callback_query(F.data.startswith("devfeed_request:"))
async def devfeed_request_callback(
    callback: CallbackQuery,
    state: FSMContext,
):
    _, raw_id = callback.data.split(":", 1)
    try:
        target_tg_id = int(raw_id)
    except ValueError:
        logger.warning(
            "devfeed_request_invalid_target user_id=%s raw_id=%s",
            callback.from_user.id,
            raw_id,
        )
        await callback.answer("Что-то пошло не так", show_alert=True)
        return

    logger.info(
        "devfeed_request_clicked from_id=%s to_id=%s",
        callback.from_user.id,
        target_tg_id,
    )

    await state.update_data(
        pending_request_target_id=target_tg_id,
        pending_request_source_message_id=callback.message.message_id,
    )

    kb = InlineKeyboardBuilder()
    kb.button(text="✍️ Написать сообщение", callback_data="devfeed_req_msg_yes")
    kb.button(text="🚀 Отправить без текста", callback_data="devfeed_req_msg_no")
    kb.button(text="❌ Отмена", callback_data="devfeed_req_cancel")
    kb.adjust(1, 1, 1)

    await callback.answer()
    await callback.message.answer(
        "Хочешь добавить приветственное сообщение к заявке этому разработчику?\n\n"
        "Можно написать короткий текст (кто ты и зачем пишешь), "
        "или отправить заявку без сообщения.",
        reply_markup=kb.as_markup(),
    )


@router.callback_query(F.data == "devfeed_req_cancel")
async def devfeed_req_cancel(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
):
    data = await state.get_data()
    target_tg_id = data.get("pending_request_target_id")
    source_msg_id = data.get("pending_request_source_message_id")

    logger.info(
        "devfeed_request_cancel from_id=%s to_id=%s source_msg_id=%s",
        callback.from_user.id,
        target_tg_id,
        source_msg_id,
    )

    await state.update_data(
        pending_request_target_id=None,
        pending_request_source_message_id=None,
    )

    await callback.answer("Отменено", show_alert=False)

    try:
        await callback.message.delete()
    except Exception:
        logger.debug(
            "devfeed_request_cancel_msg_delete_failed user_id=%s",
            callback.from_user.id,
            exc_info=True,
        )

    if source_msg_id:
        try:
            await bot.delete_message(
                chat_id=callback.message.chat.id,
                message_id=source_msg_id,
            )
        except Exception:
            logger.debug(
                "devfeed_request_source_msg_delete_failed user_id=%s msg_id=%s",
                callback.from_user.id,
                source_msg_id,
                exc_info=True,
            )

    if target_tg_id:
        profile = await get_profile(session, target_tg_id)
        if profile:
            await _send_dev_profile_card(
                source_message=callback.message,
                profile=profile,
                bot=bot,
            )


@router.callback_query(F.data == "devfeed_req_msg_no")
async def devfeed_req_msg_no(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
):
    data = await state.get_data()
    target_tg_id = data.get("pending_request_target_id")
    if not target_tg_id:
        logger.warning(
            "devfeed_req_msg_no_missing_target user_id=%s", callback.from_user.id
        )
        await callback.answer(
            "Не понял, кому отправлять заявку. Попробуй ещё раз.", show_alert=True
        )
        return

    logger.info(
        "devfeed_req_msg_no from_id=%s to_id=%s", callback.from_user.id, target_tg_id
    )

    await callback.answer()
    await _process_connection_request(
        session=session,
        bot=bot,
        from_id=callback.from_user.id,
        target_tg_id=target_tg_id,
        source_message=callback.message,
        greeting=None,
    )

    await state.update_data(
        pending_request_target_id=None,
        pending_request_source_message_id=None,
    )


@router.callback_query(F.data == "devfeed_req_msg_yes")
async def devfeed_req_msg_yes(
    callback: CallbackQuery,
    state: FSMContext,
):
    logger.info("devfeed_req_msg_yes from_id=%s", callback.from_user.id)
    await callback.answer()
    await state.set_state(DevfeedRequestStates.waiting_greeting)
    await callback.message.answer(
        "Напиши приветственное сообщение, которое я приложу к заявке.\n\n"
        "Например: кто ты, над чем работаешь и почему откликаешься.",
    )


@router.message(DevfeedRequestStates.waiting_greeting)
async def devfeed_req_greeting_message(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
):
    data = await state.get_data()
    target_tg_id = data.get("pending_request_target_id")
    if not target_tg_id:
        logger.warning(
            "devfeed_req_greeting_missing_target user_id=%s",
            message.from_user.id if message.from_user else None,
        )
        await message.answer(
            "Я потерял, кому нужно отправить заявку. Попробуй ещё раз из ленты."
        )
        await state.clear()
        return

    greeting = (message.text or "").strip()
    if len(greeting) > 500:
        await message.answer("Слишком длинно. Уложись примерно в 500 символов 🙂")
        return
    if not greeting:
        await message.answer("Сообщение пустое. Напиши хоть пару слов 🙂")
        return

    logger.info(
        "devfeed_req_greeting_entered from_id=%s to_id=%s greeting_len=%s",
        message.from_user.id,
        target_tg_id,
        len(greeting),
    )

    await _process_connection_request(
        session=session,
        bot=bot,
        from_id=message.from_user.id,
        target_tg_id=target_tg_id,
        source_message=message,
        greeting=greeting,
    )
    await state.clear()
