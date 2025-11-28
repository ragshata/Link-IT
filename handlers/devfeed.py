# handlers/devfeed.py

from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from services import (
    search_profiles_for_user,
    get_profile,
    send_connection_request,
    accept_connection_request,
    reject_connection_request,
    get_connection_request,
)
from views import format_profile_public

router = Router()


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
    - анонимное описание (без username),
    - инлайн-клавиатура:
        1) Награды
        2) Откликнуться
        3) Предыдущий / Следующий
    """
    text = format_profile_public(profile)

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
    kb.adjust(1, 1, 2)  # 1 кнопка, 1 кнопка, потом 2 в ряд

    if profile.avatar_file_id:
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
        return None, None

    if new_index < 0 or new_index >= len(ids):
        return None, None

    next_tg_id = ids[new_index]
    profile = await get_profile(session, next_tg_id)

    # пропускаем самого себя на всякий
    if profile and profile.telegram_id == requester_id:
        # пробуем сдвинуться дальше
        if new_index + 1 < len(ids):
            return await _get_devfeed_profile_at_index(
                state=state,
                session=session,
                requester_id=requester_id,
                new_index=new_index + 1,
            )
        return None, None

    await state.update_data(devfeed_index=new_index)
    return profile, new_index


# ===== старт ленты по кнопке "👥 Лента разработчиков" =====


@router.message(F.text == "👥 Лента разработчиков")
async def on_menu_devs_feed(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
):
    profiles = await search_profiles_for_user(
        session,
        requester_id=message.from_user.id,
        goal=None,
        role=None,
        limit=50,
    )

    # убрать самого себя
    profiles = [p for p in profiles if p.telegram_id != message.from_user.id]

    if not profiles:
        await message.answer(
            "Пока не нашлось ни одного подходящего профиля.\n"
            "Попробуй позже — база пополняется.",
        )
        return

    await state.update_data(
        devfeed_profile_ids=[p.telegram_id for p in profiles],
        devfeed_index=0,
    )

    await _send_dev_profile_card(
        source_message=message,
        profile=profiles[0],
        bot=bot,
    )


@router.callback_query(F.data == "devfeed_next")
async def devfeed_next_callback(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
):
    data = await state.get_data()
    index: int | None = data.get("devfeed_index", 0)
    if index is None:
        index = 0

    new_index = index + 1

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

    # шлём новую карточку
    await _send_dev_profile_card(
        source_message=callback.message,
        profile=profile,
        bot=bot,
    )

    # удаляем старую
    try:
        await callback.message.delete()
    except Exception:
        pass


@router.callback_query(F.data == "devfeed_prev")
async def devfeed_prev_callback(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
):
    data = await state.get_data()
    index: int | None = data.get("devfeed_index", 0)
    if index is None:
        index = 0

    new_index = index - 1
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

    # шлём новую карточку
    await _send_dev_profile_card(
        source_message=callback.message,
        profile=profile,
        bot=bot,
    )

    # удаляем старую
    try:
        await callback.message.delete()
    except Exception:
        pass


# ===== кнопка "🏆 Награды пользователя" =====


@router.callback_query(F.data.startswith("devfeed_rewards:"))
async def devfeed_rewards_callback(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer(
        "Раздел с наградами пока в разработке.\n"
        "В будущем здесь будут ачивки за менторство, участие в проектах и активность.",
    )


# ===== кнопка "🤝 Откликнуться" (заявка на общение) =====


@router.callback_query(F.data.startswith("devfeed_request:"))
async def devfeed_request_callback(
    callback: CallbackQuery,
    session: AsyncSession,
    bot: Bot,
):
    """
    Пользователь из ленты жмёт '🤝 Откликнуться'.
    Создаём заявку и шлём уведомление тому, кому отправляют — с фоткой и описанием,
    но БЕЗ контактов.
    """
    _, raw_id = callback.data.split(":", 1)
    try:
        target_tg_id = int(raw_id)
    except ValueError:
        await callback.answer("Что-то пошло не так", show_alert=True)
        return

    from_id = callback.from_user.id

    req, reason = await send_connection_request(
        session,
        from_id=from_id,
        to_id=target_tg_id,
    )

    if reason == "self":
        await callback.answer("Это ты сам 😄", show_alert=True)
        return

    if reason == "exists":
        await callback.answer("Заявка уже отправлена, ждём ответа.", show_alert=False)
        return

    await callback.answer("Заявка отправлена 🎯", show_alert=False)

    sender_profile = await get_profile(session, from_id)
    sender_text = format_profile_public(sender_profile)  # БЕЗ username

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

    notify_text = (
        "Тебе пришла заявка на сотрудничество в LinkIT.\n\n"
        "Профиль отправителя:\n\n"
        f"{sender_text}\n\n"
        "Контакты откроются, если ты примешь заявку."
    )

    # уведомление адресату — с фоткой, если есть
    try:
        if sender_profile and sender_profile.avatar_file_id:
            await bot.send_photo(
                chat_id=target_tg_id,
                photo=sender_profile.avatar_file_id,
                caption=notify_text,
                reply_markup=kb.as_markup(),
            )
        else:
            # тут явно пишем, что без аватара, чтобы ты видел ветку
            await bot.send_message(
                chat_id=target_tg_id,
                text=notify_text + "\n\n(У отправителя пока нет аватарки в профиле)",
                reply_markup=kb.as_markup(),
            )
    except Exception:
        # если бот не может написать (юзер не нажимал /start)
        pass

    # сообщение отправителю
    await callback.message.answer(
        "Заявка отправлена.\n\n"
        "Когда пользователь ответит, я пришлю тебе уведомление: "
        "либо контакты, либо отказ."
    )


# ===== Принять / Отклонить заявку =====


@router.callback_query(F.data.startswith("conn_accept:"))
async def connection_accept_callback(
    callback: CallbackQuery,
    session: AsyncSession,
    bot: Bot,
):
    _, raw_id = callback.data.split(":", 1)
    try:
        request_id = int(raw_id)
    except ValueError:
        await callback.answer("Неверная заявка", show_alert=True)
        return

    req = await get_connection_request(session, request_id=request_id)
    if not req:
        await callback.answer("Заявка не найдена", show_alert=True)
        return

    if req.to_telegram_id != callback.from_user.id:
        await callback.answer("Это не твоя заявка", show_alert=True)
        return

    if req.status != "pending":
        await callback.answer("Эта заявка уже обработана", show_alert=True)
        return

    req = await accept_connection_request(session, request_id=request_id)
    await callback.answer("Заявка принята ✅", show_alert=False)

    from_profile = await get_profile(session, req.from_telegram_id)
    to_profile = await get_profile(session, req.to_telegram_id)

    from_username = from_profile.username if from_profile else None
    to_username = to_profile.username if to_profile else None

    # сообщение тому, кто ПРИНЯЛ — дописываем, что заявка принята + контакт отправителя
    text = callback.message.text + "\n\nТы принял(а) эту заявку.\n"
    if from_username:
        text += f"Контакт отправителя: @{from_username}"
    else:
        text += (
            "У отправителя нет публичного @username.\n"
            "Если он напишет первым — отвечай прямо в переписке."
        )
    await callback.message.edit_text(text)

    # уведомление ОТПРАВИТЕЛЮ — фотка + краткое описание того, кто принял + его контакт
    if to_profile:
        public_text = format_profile_public(to_profile)
        header = "Твою заявку приняли 🎉\n\n"
        contact_line = (
            f"Можешь писать: @{to_username}"
            if to_username
            else "Пользователь принял заявку, но у него нет публичного @username.\n"
            "Если он напишет первым — просто отвечай."
        )
        notify_text = (
            f"{header}"
            f"Тот, кто принял заявку:\n\n"
            f"{public_text}\n\n"
            f"{contact_line}"
        )

        try:
            if to_profile.avatar_file_id:
                await bot.send_photo(
                    chat_id=req.from_telegram_id,
                    photo=to_profile.avatar_file_id,
                    caption=notify_text,
                )
            else:
                await bot.send_message(
                    chat_id=req.from_telegram_id,
                    text=notify_text,
                )
        except Exception:
            pass
    else:
        # fallback, если профиль почему-то не нашли
        notify_text = "Твою заявку приняли 🎉\n\n"
        if to_username:
            notify_text += f"Можешь писать: @{to_username}"
        else:
            notify_text += (
                "Пользователь принял заявку, но у него нет публичного @username.\n"
                "Если он напишет первым — просто отвечай."
            )
        try:
            await bot.send_message(
                chat_id=req.from_telegram_id,
                text=notify_text,
            )
        except Exception:
            pass


@router.callback_query(F.data.startswith("conn_reject:"))
async def connection_reject_callback(
    callback: CallbackQuery,
    session: AsyncSession,
    bot: Bot,
):
    _, raw_id = callback.data.split(":", 1)
    try:
        request_id = int(raw_id)
    except ValueError:
        await callback.answer("Неверная заявка", show_alert=True)
        return

    req = await get_connection_request(session, request_id=request_id)
    if not req:
        await callback.answer("Заявка не найдена", show_alert=True)
        return

    if req.to_telegram_id != callback.from_user.id:
        await callback.answer("Это не твоя заявка", show_alert=True)
        return

    if req.status != "pending":
        await callback.answer("Эта заявка уже обработана", show_alert=True)
        return

    await reject_connection_request(session, request_id=request_id)
    await callback.answer("Заявка отклонена", show_alert=False)

    await callback.message.edit_text(
        callback.message.text + "\n\nТы отклонил(а) эту заявку."
    )

    try:
        await bot.send_message(
            chat_id=req.from_telegram_id,
            text="К сожалению, твою заявку отклонили 🙁",
        )
    except Exception:
        pass
