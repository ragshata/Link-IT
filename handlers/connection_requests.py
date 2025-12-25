# handlers/connection_requests.py

from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from repositories import set_connection_request_status
from services import (
    get_profile,
    get_project,
    get_connection_request,
)
from views import format_profile_public, html_safe

router = Router()


@router.callback_query(F.data.startswith("conn_accept:"))
async def conn_accept_callback(
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

    # ✅ кнопку может нажать только получатель
    if req.to_telegram_id != callback.from_user.id:
        await callback.answer("Это не твоя заявка", show_alert=True)
        return

    if req.status != "pending":
        await callback.answer("Эта заявка уже обработана", show_alert=True)
        return

    # ====== ПРОЕКТНАЯ ЗАЯВКА ======
    if req.project_id is not None:
        project = await get_project(session, req.project_id)

        # Лимит команды
        if project and project.team_limit:
            current = project.current_members or 1
            if current >= project.team_limit:
                await callback.answer("Команда уже укомплектована", show_alert=True)
                return

        # accepted + responded_at (внутри репозитория)
        req = await set_connection_request_status(
            session,
            request_id=request_id,
            status="accepted",
        )
        if not req:
            await callback.answer("Заявка не найдена", show_alert=True)
            return

        # Увеличиваем счетчик участников
        if project:
            current = project.current_members or 1
            project.current_members = current + 1
            await session.commit()
            await session.refresh(project)

        from_profile = await get_profile(session, req.from_telegram_id)  # кандидат
        to_profile = await get_profile(session, req.to_telegram_id)  # владелец

        from_username = from_profile.username if from_profile else None
        owner_username = to_profile.username if to_profile else None

        # HTML-safe название проекта (проект создаёт пользователь)
        project_title = (
            html_safe(project.title, default="Проект") if project else "Проект"
        )

        # Убираем кнопки + помечаем как принято
        base_text = callback.message.text or callback.message.caption or ""
        suffix = "\n\n✅ Заявка принята.\n"
        new_text = (base_text + suffix) if base_text else suffix

        try:
            if callback.message.text is not None:
                await callback.message.edit_text(new_text, reply_markup=None)
            else:
                await callback.message.edit_caption(new_text, reply_markup=None)
        except Exception:
            pass

        # Сообщение владельцу (дубль подтверждения)
        try:
            cand_contact = (
                f"@{from_username}" if from_username else f"id: {req.from_telegram_id}"
            )
            owner_text = (
                f"Ты принял(а) заявку в проект «{project_title}» 🤝\n\n"
                f"Кандидат: {cand_contact}"
            )
            await bot.send_message(chat_id=req.to_telegram_id, text=owner_text)
        except Exception:
            pass

        # Сообщение кандидату
        try:
            contact = (
                f"@{owner_username}" if owner_username else f"id: {req.to_telegram_id}"
            )
            applicant_text = (
                f"Тебя приняли в проект «{project_title}» 🎉\n\n"
                f"Можешь писать создателю проекта: {contact}"
            )
            await bot.send_message(chat_id=req.from_telegram_id, text=applicant_text)
        except Exception:
            pass

        await callback.answer("Заявка принята ✅", show_alert=False)
        return

    # ====== ОБЫЧНЫЙ КОННЕКТ ======
    req = await set_connection_request_status(
        session,
        request_id=request_id,
        status="accepted",
    )
    if not req:
        await callback.answer("Заявка не найдена", show_alert=True)
        return

    from_profile = await get_profile(session, req.from_telegram_id)
    to_profile = await get_profile(session, req.to_telegram_id)

    to_username = to_profile.username if to_profile else None

    # Убираем кнопки + помечаем как принято
    base_text = callback.message.text or callback.message.caption or ""
    suffix = "\n\n✅ Заявка принята.\n"
    new_text = (base_text + suffix) if base_text else suffix

    try:
        if callback.message.text is not None:
            await callback.message.edit_text(new_text, reply_markup=None)
        else:
            await callback.message.edit_caption(new_text, reply_markup=None)
    except Exception:
        pass

    # Сообщение принявшему
    try:
        sender_contact = (
            f"@{from_profile.username}"
            if (from_profile and from_profile.username)
            else f"id: {req.from_telegram_id}"
        )
        await bot.send_message(
            chat_id=req.to_telegram_id,
            text=f"Контакт отправителя: {sender_contact}",
        )
    except Exception:
        pass

    # Сообщение отправителю
    try:
        header = "Твою заявку приняли 🎉\n\n"
        public_text = (
            format_profile_public(to_profile) if to_profile else "Профиль не найден"
        )

        if to_username:
            contact_line = f"Можешь писать: @{to_username}"
        else:
            contact_line = (
                "Пользователь принял заявку, но у него нет публичного @username.\n"
                f"Его внутренний ID: {req.to_telegram_id}\n"
                "Если он напишет первым, просто отвечай."
            )

        notify_text = (
            f"{header}Тот, кто принял заявку:\n\n{public_text}\n\n{contact_line}"
        )
        await bot.send_message(chat_id=req.from_telegram_id, text=notify_text)
    except Exception:
        pass

    await callback.answer("Заявка принята ✅", show_alert=False)


@router.callback_query(F.data.startswith("conn_reject:"))
async def conn_reject_callback(
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

    # ✅ кнопку может нажать только получатель
    if req.to_telegram_id != callback.from_user.id:
        await callback.answer("Это не твоя заявка", show_alert=True)
        return

    if req.status != "pending":
        await callback.answer("Эта заявка уже обработана", show_alert=True)
        return

    req = await set_connection_request_status(
        session,
        request_id=request_id,
        status="rejected",
    )
    if not req:
        await callback.answer("Заявка не найдена", show_alert=True)
        return

    # Убираем кнопки + помечаем как отклонено
    base_text = callback.message.text or callback.message.caption or ""
    suffix = "\n\n❌ Заявка отклонена.\n"
    new_text = (base_text + suffix) if base_text else suffix

    try:
        if callback.message.text is not None:
            await callback.message.edit_text(new_text, reply_markup=None)
        else:
            await callback.message.edit_caption(new_text, reply_markup=None)
    except Exception:
        pass

    # Уведомляем отправителя
    try:
        await bot.send_message(
            chat_id=req.from_telegram_id,
            text="Твою заявку отклонили. Не принимай это близко к сердцу, это просто люди.",
        )
    except Exception:
        pass

    await callback.answer("Отклонено ❌", show_alert=False)
