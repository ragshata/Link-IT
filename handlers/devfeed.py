from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from services import (
    search_profiles_for_user,  # можно удалить, если нигде не используешь
    get_profile,
    send_connection_request,
    accept_connection_request,
    reject_connection_request,
    get_connection_request,
    get_project,
)
from views import format_profile_public

router = Router()


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


# ===== Вспомогалка: отправка заявки (общая для обоих сценариев) =====


async def _process_connection_request(
    *,
    session: AsyncSession,
    bot: Bot,
    from_id: int,
    target_tg_id: int,
    source_message: Message,
    greeting: str | None = None,
):
    """
    Общая логика отправки заявки:
    - создаём ConnectionRequest
    - уведомляем адресата
    - уведомляем отправителя
    """
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

    if greeting:
        notify_text = (
            "Тебе пришла заявка на сотрудничество в Link IT.\n\n"
            "Профиль отправителя:\n\n"
            f"{sender_text}\n\n"
            "Сообщение от отправителя:\n"
            f"{greeting}\n\n"
            "Контакты откроются, если ты примешь заявку."
        )
    else:
        notify_text = (
            "Тебе пришла заявка на сотрудничество в Link IT.\n\n"
            "Профиль отправителя:\n\n"
            f"{sender_text}\n\n"
            "Контакты откроются, если ты примешь заявку."
        )

    # уведомление адресату — с фоткой, если есть
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
    except Exception:
        # если бот не может написать (юзер не нажимал /start) — игнорируем
        pass

    # сообщение отправителю
    await source_message.answer(
        "Заявка отправлена.\n\n"
        "Когда пользователь ответит, я пришлю тебе уведомление: "
        "либо контакты, либо отказ."
    )


# ===== кнопка "🤝 Откликнуться" (заявка на общение) =====


@router.callback_query(F.data.startswith("devfeed_request:"))
async def devfeed_request_callback(
    callback: CallbackQuery,
    state: FSMContext,
):
    """
    Первый шаг: спрашиваем, хочет ли пользователь добавить приветственное сообщение.
    """
    _, raw_id = callback.data.split(":", 1)
    try:
        target_tg_id = int(raw_id)
    except ValueError:
        await callback.answer("Что-то пошло не так", show_alert=True)
        return

    # сохраняем, к кому откликаемся и id карточки из ленты
    await state.update_data(
        pending_request_target_id=target_tg_id,
        pending_request_source_message_id=callback.message.message_id,
    )

    kb = InlineKeyboardBuilder()
    kb.button(
        text="✍️ Написать сообщение",
        callback_data="devfeed_req_msg_yes",
    )
    kb.button(
        text="🚀 Отправить без текста",
        callback_data="devfeed_req_msg_no",
    )
    kb.button(
        text="❌ Отмена",
        callback_data="devfeed_req_cancel",
    )
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

    # очищаем временные данные
    await state.update_data(
        pending_request_target_id=None,
        pending_request_source_message_id=None,
    )

    await callback.answer("Отменено", show_alert=False)

    # удаляем сообщение с выбором (написать / без текста / отмена)
    try:
        await callback.message.delete()
    except Exception:
        pass

    # удаляем старую карточку из ленты, если знаем её message_id
    if source_msg_id:
        try:
            await bot.delete_message(
                chat_id=callback.message.chat.id,
                message_id=source_msg_id,
            )
        except Exception:
            pass

    # заново показываем карточку этого же разработчика
    if target_tg_id:
        profile = await get_profile(session, target_tg_id)
        if profile:
            await _send_dev_profile_card(
                source_message=callback.message,  # чат тот же
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
        await callback.answer(
            "Не понял, кому отправлять заявку. Попробуй ещё раз.", show_alert=True
        )
        return

    await callback.answer()
    await _process_connection_request(
        session=session,
        bot=bot,
        from_id=callback.from_user.id,
        target_tg_id=target_tg_id,
        source_message=callback.message,
        greeting=None,
    )
    # очищаем и цель, и message_id
    await state.update_data(
        pending_request_target_id=None,
        pending_request_source_message_id=None,
    )


@router.callback_query(F.data == "devfeed_req_msg_yes")
async def devfeed_req_msg_yes(
    callback: CallbackQuery,
    state: FSMContext,
):
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
        await message.answer(
            "Я потерял, кому нужно отправить заявку. Попробуй ещё раз из ленты.",
        )
        await state.clear()
        return

    greeting = (message.text or "").strip()
    if not greeting:
        await message.answer("Сообщение пустое. Напиши хоть пару слов 🙂")
        return

    await _process_connection_request(
        session=session,
        bot=bot,
        from_id=message.from_user.id,
        target_tg_id=target_tg_id,
        source_message=message,
        greeting=greeting,
    )
    await state.clear()


# ===== Принять / Отклонить заявку =====


@router.callback_query(F.data.startswith("conn_accept:"))
async def connection_accept_callback(
    callback: CallbackQuery,
    session: AsyncSession,
    bot: Bot,
):
    """
    Принятие заявки:
    - либо обычный коннект (лента разработчиков),
    - либо участие в проекте (если request.project_id не пустой).
    """
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

    # Обновляем статус
    req = await accept_connection_request(session, request_id=request_id)
    await callback.answer("Заявка принята ✅", show_alert=False)

    # Ветвим логику:
    if req.project_id is None:
        # ===== Обычный коннект (лента разработчиков) =====
        from_profile = await get_profile(session, req.from_telegram_id)
        to_profile = await get_profile(session, req.to_telegram_id)

        from_username = from_profile.username if from_profile else None
        to_username = to_profile.username if to_profile else None

        base_text = callback.message.text or callback.message.caption or ""
        suffix = "\n\nТы принял(а) эту заявку.\n"

        if from_username:
            suffix += f"Контакт разработчика: @{from_username}"
        else:
            suffix += (
                "У разработчика нет публичного @username.\n"
                f"Его внутренний ID: {req.from_telegram_id}\n"
                "Он сможет написать тебе первым, а ты уже ответишь ему."
            )

        new_text = (base_text + suffix) if base_text else suffix

        try:
            if callback.message.text is not None:
                await callback.message.edit_text(new_text)
            else:
                await callback.message.edit_caption(new_text)
        except Exception:
            pass

        # Отдельное сообщение тому, кто принял
        try:
            if from_username:
                acceptor_text = (
                    "Ты принял(а) заявку 🤝\n\n"
                    f"Контакт разработчика: @{from_username}\n"
                    "Напиши ему в личку и продолжите общение напрямую."
                )
            else:
                acceptor_text = (
                    "Ты принял(а) заявку 🤝\n\n"
                    "У разработчика нет публичного @username.\n"
                    f"Его внутренний ID: {req.from_telegram_id}\n"
                    "Он сможет написать тебе первым, а ты уже продолжишь диалог."
                )

            await bot.send_message(
                chat_id=req.to_telegram_id,
                text=acceptor_text,
            )
        except Exception:
            pass

        # Уведомляем отправителя
        if to_profile:
            public_text = format_profile_public(to_profile)
            header = "Твою заявку приняли 🎉\n\n"

            if to_username:
                contact_line = f"Можешь писать: @{to_username}"
            else:
                contact_line = (
                    "Пользователь принял заявку, но у него нет публичного @username.\n"
                    f"Его внутренний ID: {req.to_telegram_id}\n"
                    "Если он напишет первым — просто отвечай."
                )

            notify_text = (
                f"{header}"
                f"Тот, кто принял заявку:\n\n"
                f"{public_text}\n\n"
                f"{contact_line}"
            )
        else:
            notify_text = "Твою заявку приняли 🎉\n\n"
            if to_username:
                notify_text += f"Можешь писать: @{to_username}"
            else:
                notify_text += (
                    "Пользователь принял заявку, но у него нет публичного @username.\n"
                    f"Его внутренний ID: {req.to_telegram_id}\n"
                    "Если он напишет первым — просто отвечай."
                )

        try:
            await bot.send_message(
                chat_id=req.from_telegram_id,
                text=notify_text,
            )
        except Exception:
            pass

        return

    # ===== Заявка на ПРОЕКТ =====
    project = await get_project(session, req.project_id)
    from_profile = await get_profile(session, req.from_telegram_id)  # кандидат
    to_profile = await get_profile(session, req.to_telegram_id)  # владелец

    from_username = from_profile.username if from_profile else None
    owner_username = to_profile.username if to_profile else None if to_profile else None

    # Обновляем текст сообщения у владельца
    base_text = callback.message.text or callback.message.caption or ""
    suffix = "\n\nТы принял(а) эту заявку в проект.\n"
    new_text = (base_text + suffix) if base_text else suffix

    try:
        if callback.message.text is not None:
            await callback.message.edit_text(new_text)
        else:
            await callback.message.edit_caption(new_text)
    except Exception:
        pass

    # Обновляем счётчик участников проекта
    if project:
        current = project.current_members or 1
        if project.team_limit:
            if current < project.team_limit:
                project.current_members = current + 1
            else:
                project.current_members = current
        else:
            project.current_members = current + 1

        await session.commit()
        await session.refresh(project)

    # Сообщение владельцу (принявшему)
    try:
        cand_contact = (
            f"@{from_username}" if from_username else f"id: {req.from_telegram_id}"
        )
        owner_text = (
            f"Ты принял(а) заявку в проект "
            f"«{project.title if project else 'Проект'}» 🤝\n\n"
            f"Кандидат: {cand_contact}\n"
            "Можешь продолжить с ним общение напрямую или в чате проекта."
        )
        await bot.send_message(
            chat_id=req.to_telegram_id,
            text=owner_text,
        )
    except Exception:
        pass

    # Сообщение кандидату
    try:
        if project and project.chat_link:
            # Есть чат — отправляем только ссылку на беседу
            applicant_text = (
                f"Тебя приняли в проект «{project.title}» 🎉\n\n"
                f"Присоединяйся к чату проекта:\n{project.chat_link}"
            )
        else:
            # Чата нет — даём контакт создателя
            if owner_username:
                contact = f"@{owner_username}"
            else:
                contact = f"id: {req.to_telegram_id}"

            applicant_text = (
                f"Тебя приняли в проект "
                f"«{project.title if project else 'Проект'}» 🎉\n\n"
                f"Можешь писать создателю проекта: {contact}"
            )

        await bot.send_message(
            chat_id=req.from_telegram_id,
            text=applicant_text,
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

    base_text = callback.message.text or callback.message.caption or ""
    suffix = "\n\nТы отклонил(а) эту заявку."
    new_text = (base_text + suffix) if base_text else suffix

    try:
        if callback.message.text is not None:
            await callback.message.edit_text(new_text)
        else:
            await callback.message.edit_caption(new_text)
    except Exception:
        pass

    try:
        await bot.send_message(
            chat_id=req.from_telegram_id,
            text="К сожалению, твою заявку отклонили 🙁",
        )
    except Exception:
        pass
