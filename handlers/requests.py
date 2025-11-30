# handlers/requests.py

from datetime import datetime

from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from models import ConnectionRequest, Project
from services import get_profile, get_project
from repositories import (
    get_connection_request_by_id,
)

router = Router()


async def _finalize_request_status(
    session: AsyncSession,
    req: ConnectionRequest,
    status: str,
) -> ConnectionRequest:
    req.status = status
    req.responded_at = datetime.utcnow()
    await session.commit()
    await session.refresh(req)
    return req


@router.callback_query(F.data.startswith("conn_accept:"))
async def conn_accept_callback(
    callback: CallbackQuery,
    session: AsyncSession,
    bot: Bot,
):
    """
    Владелец проекта/профиля нажал «Принять».
    - ставим статус accepted
    - если это заявка на проект, увеличиваем current_members
    - шлём контакты:
        * владельцу — контакты кандидата
        * кандидату — ссылку на чат проекта или @username владельца
    """
    _, raw_id = callback.data.split(":", 1)
    try:
        req_id = int(raw_id)
    except ValueError:
        await callback.answer("Некорректная заявка", show_alert=True)
        return

    req = await get_connection_request_by_id(session, req_id)
    if not req:
        await callback.answer("Заявка не найдена", show_alert=True)
        return

    # защищаемся от повторных нажатий
    if req.status != "pending":
        await callback.answer("Заявка уже обработана", show_alert=False)
        return

    # фиксируем статус
    await _finalize_request_status(session, req, "accepted")

    owner_id = req.to_telegram_id
    applicant_id = req.from_telegram_id

    # --- если это заявка на проект ---
    project: Project | None = None
    if req.project_id:
        project = await session.get(Project, req.project_id)
        if project:
            # увеличиваем количество участников
            current = project.current_members or 1
            project.current_members = current + 1
            await session.commit()
            await session.refresh(project)

    # --- контакты кандидата для владельца ---

    applicant_profile = await get_profile(session, applicant_id)

    if applicant_profile and applicant_profile.username:
        contact_for_owner = f"@{applicant_profile.username}"
    else:
        # запасной вариант, если нет username
        contact_for_owner = f"tg id: {applicant_id}"

    if project:
        owner_text = (
            f"Ты принял заявку в проект «{project.title}» ✅\n\n"
            f"Контакты кандидата:\n{contact_for_owner}"
        )
    else:
        owner_text = (
            "Ты принял заявку ✅\n\n" f"Контакты кандидата:\n{contact_for_owner}"
        )

    await callback.message.answer(owner_text)

    # --- контакты проекта/владельца для кандидата ---

    owner_profile = await get_profile(session, owner_id)

    # если у проекта есть ссылка на чат — даём её,
    # иначе показываем @username владельца
    chat_link: str | None = project.chat_link if project else None

    if chat_link:
        contact_for_applicant = chat_link
    elif owner_profile and owner_profile.username:
        contact_for_applicant = f"@{owner_profile.username}"
    else:
        contact_for_applicant = f"tg id: {owner_id}"

    if project:
        applicant_text = (
            f"Тебя приняли в проект «{project.title}» 🎉\n\n"
            f"Связаться с командой можно так:\n{contact_for_applicant}"
        )
    else:
        applicant_text = (
            "Твою заявку приняли 🎉\n\n"
            f"Вот контакт для связи:\n{contact_for_applicant}"
        )

    try:
        await bot.send_message(chat_id=applicant_id, text=applicant_text)
    except Exception:
        # кандидат не нажимал /start или заблокировал бота — не критично
        pass

    await callback.answer("Заявка принята", show_alert=False)


@router.callback_query(F.data.startswith("conn_reject:"))
async def conn_reject_callback(
    callback: CallbackQuery,
    session: AsyncSession,
    bot: Bot,
):
    """
    Владелец нажал «Отклонить».
    - ставим status=rejected
    - уведомляем кандидата, что отказ
    """
    _, raw_id = callback.data.split(":", 1)
    try:
        req_id = int(raw_id)
    except ValueError:
        await callback.answer("Некорректная заявка", show_alert=True)
        return

    req = await get_connection_request_by_id(session, req_id)
    if not req:
        await callback.answer("Заявка не найдена", show_alert=True)
        return

    if req.status != "pending":
        await callback.answer("Заявка уже обработана", show_alert=False)
        return

    await _finalize_request_status(session, req, "rejected")

    # уведомляем кандидата
    project: Project | None = None
    if req.project_id:
        project = await session.get(Project, req.project_id)

    if project:
        text = (
            f"Заявка в проект «{project.title}» отклонена.\n"
            "Не расстраивайся, в ленте ещё много проектов, где тебя будут рады видеть 🙂"
        )
    else:
        text = (
            "Заявка отклонена.\n"
            "Не сдавайся — попробуй откликнуться на других разработчиков или проекты 🙂"
        )

    try:
        await bot.send_message(chat_id=req.from_telegram_id, text=text)
    except Exception:
        pass

    await callback.answer("Заявка отклонена", show_alert=False)
