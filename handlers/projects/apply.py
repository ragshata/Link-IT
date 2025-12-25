import logging

from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from services import get_profile, get_project, send_project_request
from views import format_project_card, format_profile_public, html_safe

router = Router()
logger = logging.getLogger(__name__)


class ProjectApplyStates(StatesGroup):
    waiting_greeting = State()


async def _process_project_connection_request(
    *,
    session: AsyncSession,
    bot: Bot,
    from_id: int,
    project_id: int,
    project_owner_id: int,
    source_message: Message,
    greeting: str | None = None,
):
    logger.info(
        "project_request_attempt from_id=%s project_id=%s owner_id=%s has_greeting=%s",
        from_id,
        project_id,
        project_owner_id,
        bool(greeting),
    )

    req, reason = await send_project_request(
        session,
        from_id=from_id,
        to_id=project_owner_id,
        project_id=project_id,
    )

    if reason == "self":
        await source_message.answer("Это твой проект 😄")
        return

    if reason == "exists":
        await source_message.answer(
            "Ты уже отправлял заявку в этот проект, ждём ответа."
        )
        return

    if reason == "limit":
        await source_message.answer(
            "Ты достиг лимита заявок на сегодня.\n\n"
            f"Сейчас лимит — {settings.max_connection_requests_per_day}, "
            "завтра счётчик обнулится 🙂",
        )
        return

    project = await get_project(session, project_id)
    project_text = format_project_card(project) if project else "Проект не найден"

    sender_profile = await get_profile(session, from_id)
    sender_text = format_profile_public(sender_profile)

    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Принять", callback_data=f"conn_accept:{req.id}")
    kb.button(text="❌ Отклонить", callback_data=f"conn_reject:{req.id}")
    kb.adjust(2)

    notify_text = (
        "Тебе пришла заявка в проект в Link IT.\n\n"
        "Проект:\n\n"
        f"{project_text}\n\n"
        "Профиль кандидата:\n\n"
        f"{sender_text}\n\n"
        "Контакты откроются, если ты примешь заявку."
    )

    if greeting:
        notify_text += f"\nСообщение от кандидата:\n{html_safe(greeting)}\n"

    try:
        if sender_profile and getattr(sender_profile, "avatar_file_id", None):
            await bot.send_photo(
                chat_id=project_owner_id,
                photo=sender_profile.avatar_file_id,
                caption=notify_text,
                reply_markup=kb.as_markup(),
            )
        else:
            await bot.send_message(
                chat_id=project_owner_id,
                text=notify_text + "\n\n(У кандидата пока нет аватарки в профиле)",
                reply_markup=kb.as_markup(),
            )

        logger.info(
            "project_request_notification_sent from_id=%s owner_id=%s req_id=%s project_id=%s",
            from_id,
            project_owner_id,
            getattr(req, "id", None),
            project_id,
        )
    except Exception:
        logger.debug(
            "project_request_notification_failed from_id=%s owner_id=%s req_id=%s project_id=%s",
            from_id,
            project_owner_id,
            getattr(req, "id", None),
            project_id,
            exc_info=True,
        )

    await source_message.answer(
        "Заявка в проект отправлена.\n\n"
        "Когда владелец проекта ответит, я пришлю тебе уведомление."
    )


@router.callback_query(F.data.startswith("project_apply:"))
async def project_apply_callback(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
):
    _, raw_project_id = callback.data.split(":", 1)
    try:
        project_id = int(raw_project_id)
    except ValueError:
        await callback.answer("Некорректный проект", show_alert=True)
        return

    project = await get_project(session, project_id)
    if not project:
        await callback.answer("Проект не найден", show_alert=True)
        return

    if project.owner_telegram_id == callback.from_user.id:
        await callback.answer("Это твой проект 😄", show_alert=True)
        return

    # лимит команды: если указан и переполнен
    if (
        project.team_limit
        and project.current_members
        and project.current_members >= project.team_limit
    ):
        await callback.answer("Команда уже укомплектована", show_alert=True)
        return

    await state.update_data(
        pending_project_id=project_id,
        pending_project_owner_id=project.owner_telegram_id,
        pending_project_source_message_id=callback.message.message_id,
    )

    kb = InlineKeyboardBuilder()
    kb.button(text="✍️ Написать сообщение", callback_data="project_req_msg_yes")
    kb.button(text="🚀 Отправить без текста", callback_data="project_req_msg_no")
    kb.button(text="❌ Отмена", callback_data="project_req_cancel")
    kb.adjust(1, 1, 1)

    await callback.answer()
    await callback.message.answer(
        "Хочешь добавить сообщение к заявке в проект?\n\n"
        "Можно написать короткий текст (кто ты и чем можешь помочь), "
        "или отправить заявку без сообщения.",
        reply_markup=kb.as_markup(),
    )


@router.callback_query(F.data == "project_req_cancel")
async def project_req_cancel(
    callback: CallbackQuery,
    state: FSMContext,
    bot: Bot,
):
    data = await state.get_data()
    source_msg_id = data.get("pending_project_source_message_id")

    await state.update_data(
        pending_project_id=None,
        pending_project_owner_id=None,
        pending_project_source_message_id=None,
    )

    await callback.answer("Отменено", show_alert=False)

    try:
        await callback.message.delete()
    except Exception:
        logger.debug(
            "project_req_cancel_msg_delete_failed user_id=%s",
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
                "project_req_source_msg_delete_failed user_id=%s msg_id=%s",
                callback.from_user.id,
                source_msg_id,
                exc_info=True,
            )


@router.callback_query(F.data == "project_req_msg_no")
async def project_req_msg_no(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
):
    data = await state.get_data()
    project_id = data.get("pending_project_id")
    owner_id = data.get("pending_project_owner_id")

    if not project_id or not owner_id:
        await callback.answer(
            "Не понял, куда отправлять заявку. Попробуй ещё раз.", show_alert=True
        )
        return

    await callback.answer()

    await _process_project_connection_request(
        session=session,
        bot=bot,
        from_id=callback.from_user.id,
        project_id=project_id,
        project_owner_id=owner_id,
        source_message=callback.message,
        greeting=None,
    )

    await state.update_data(
        pending_project_id=None,
        pending_project_owner_id=None,
        pending_project_source_message_id=None,
    )


@router.callback_query(F.data == "project_req_msg_yes")
async def project_req_msg_yes(
    callback: CallbackQuery,
    state: FSMContext,
):
    await callback.answer()
    await state.set_state(ProjectApplyStates.waiting_greeting)
    await callback.message.answer(
        "Напиши сообщение, которое я приложу к заявке.\n\n"
        "Например: кто ты, какой опыт, чем готов помочь, сколько времени есть.",
    )


@router.message(ProjectApplyStates.waiting_greeting)
async def project_req_greeting_message(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
):
    data = await state.get_data()
    project_id = data.get("pending_project_id")
    owner_id = data.get("pending_project_owner_id")

    if not project_id or not owner_id:
        await message.answer(
            "Я потерял, куда отправлять заявку. Попробуй ещё раз из ленты проектов."
        )
        await state.clear()
        return

    greeting = (message.text or "").strip()
    if not greeting:
        await message.answer("Сообщение пустое. Напиши хоть пару слов 🙂")
        return

    await _process_project_connection_request(
        session=session,
        bot=bot,
        from_id=message.from_user.id,
        project_id=project_id,
        project_owner_id=owner_id,
        source_message=message,
        greeting=greeting,
    )

    await state.clear()
