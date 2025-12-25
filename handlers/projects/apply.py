from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession
import logging

from config import settings
from services import send_connection_request, get_profile, get_project
from views import (
    format_profile_public,
    format_project_card,
)  # format_project_card используем в нотификации

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
    source_message: Message,
    greeting: str | None = None,
):
    logger.info(
        "project_request_process_start user_id=%s project_id=%s has_greeting=%s",
        from_id,
        project_id,
        bool(greeting),
    )

    # 1. Проверяем, что проект существует
    project = await get_project(session, project_id)
    if not project:
        logger.warning(
            "project_request_project_not_found user_id=%s project_id=%s",
            from_id,
            project_id,
        )
        await source_message.answer("Проект не найден. Попробуй позже.")
        return

    to_id = project.owner_telegram_id

    # 2. Отправляем стандартную заявку (user -> user)
    req, reason = await send_connection_request(
        session,
        from_id=from_id,
        to_id=to_id,
    )

    if reason == "self":
        logger.info(
            "project_request_self user_id=%s project_id=%s",
            from_id,
            project_id,
        )
        await source_message.answer("Это твой проект 😄")
        return

    if reason == "exists":
        logger.info(
            "project_request_exists user_id=%s project_id=%s owner_id=%s",
            from_id,
            project_id,
            to_id,
        )
        await source_message.answer(
            "Ты уже отправлял заявку этому человеку. Ждём ответа.",
        )
        return

    if reason == "limit":
        logger.info(
            "project_request_limit_reached user_id=%s project_id=%s limit=%s",
            from_id,
            project_id,
            settings.max_connection_requests_per_day,
        )
        await source_message.answer(
            "Ты достиг лимита заявок на сегодня.\n\n"
            f"Сейчас лимит — {settings.max_connection_requests_per_day}, "
            "завтра счётчик обнулится 🙂",
        )
        return

    # 3. Привязываем заявку к конкретному проекту
    req.project_id = project.id
    await session.commit()
    await session.refresh(req)

    logger.info(
        "project_request_created request_id=%s user_id=%s project_id=%s owner_id=%s",
        req.id,
        from_id,
        project.id,
        to_id,
    )

    # 4. Собираем данные по кандидату
    applicant_profile = await get_profile(session, from_id)

    if applicant_profile:
        applicant_text = format_profile_public(applicant_profile)
    else:
        # На всякий случай, если профиля нет (не должны сюда попадать, но вдруг)
        applicant_text = f"Telegram ID: {from_id}"

    # Текст проекта (карточка как в ленте)
    project_text = format_project_card(project)

    # 5. Собираем и отправляем уведомление владельцу проекта
    notify_text = (
        "На твой проект в Link IT пришла новая заявка.\n\n"
        f"Проект:\n{project_text}\n\n"
        "Кандидат:\n\n"
        f"{applicant_text}\n"
    )

    if greeting:
        notify_text += f"\nСообщение от кандидата:\n{greeting}\n"

    # было про "контакты откроются" — убираем, чтобы не путать
    notify_text += (
        "\nЕсли ты примешь заявку, я пришлю кандидату контакты проекта "
        "и ссылку на беседу (если она указана)."
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
        if applicant_profile and getattr(applicant_profile, "avatar_file_id", None):
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
            "project_request_notify_owner_sent request_id=%s owner_id=%s",
            req.id,
            to_id,
        )
    except Exception:
        # владелец не нажимал /start или заблокировал бота — не критично
        logger.debug(
            "project_request_notify_owner_failed request_id=%s owner_id=%s",
            req.id,
            to_id,
            exc_info=True,
        )

    # 6. Сообщаем кандидату
    await source_message.answer(
        "Заявка на участие в проекте отправлена.\n\n"
        "Когда владелец проекта ответит, я пришлю тебе уведомление: "
        "либо контакты / ссылку на беседу, либо отказ."
    )
    logger.info(
        "project_request_user_notified request_id=%s user_id=%s",
        req.id,
        from_id,
    )


@router.callback_query(F.data.startswith("proj_apply:"))
async def proj_apply_callback(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
):
    """
    Нажали "🤝 Откликнуться на проект" — спрашиваем про комментарий.
    """
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

    logger.info(
        "project_apply_clicked user_id=%s project_id=%s owner_id=%s",
        callback.from_user.id,
        project_id,
        project.owner_telegram_id,
    )

    await state.update_data(
        pending_project_id=project_id,
    )

    kb = InlineKeyboardBuilder()
    kb.button(
        text="✍️ Написать сообщение",
        callback_data="proj_req_msg_yes",
    )
    kb.button(
        text="🚀 Отправить без текста",
        callback_data="proj_req_msg_no",
    )
    kb.button(
        text="❌ Отмена",
        callback_data="proj_req_cancel",
    )
    kb.adjust(1, 1, 1)

    await callback.answer()
    await callback.message.answer(
        "Хочешь добавить сообщение к отклику на этот проект?\n\n"
        "Можно коротко написать, кто ты и чем хочешь помочь, "
        "или отправить заявку без сообщения.",
        reply_markup=kb.as_markup(),
    )


@router.callback_query(F.data == "proj_req_cancel")
async def proj_req_cancel(
    callback: CallbackQuery,
    state: FSMContext,
):
    data = await state.get_data()
    project_id = data.get("pending_project_id")

    logger.info(
        "project_apply_cancel user_id=%s project_id=%s",
        callback.from_user.id,
        project_id,
    )

    await state.update_data(pending_project_id=None)
    await callback.answer("Отменено", show_alert=False)
    try:
        await callback.message.delete()
    except Exception:
        logger.debug(
            "project_apply_cancel_msg_delete_failed user_id=%s",
            callback.from_user.id,
            exc_info=True,
        )


@router.callback_query(F.data == "proj_req_msg_no")
async def proj_req_msg_no(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
):
    data = await state.get_data()
    project_id = data.get("pending_project_id")
    if not project_id:
        logger.warning(
            "project_apply_no_project_in_state user_id=%s",
            callback.from_user.id,
        )
        await callback.answer(
            "Не понял, к какому проекту откликаться. Попробуй ещё раз.",
            show_alert=True,
        )
        return

    logger.info(
        "project_apply_without_message user_id=%s project_id=%s",
        callback.from_user.id,
        project_id,
    )

    await callback.answer()
    await _process_project_connection_request(
        session=session,
        bot=bot,
        from_id=callback.from_user.id,
        project_id=project_id,
        source_message=callback.message,
        greeting=None,
    )
    await state.update_data(pending_project_id=None)


@router.callback_query(F.data == "proj_req_msg_yes")
async def proj_req_msg_yes(
    callback: CallbackQuery,
    state: FSMContext,
):
    logger.info(
        "project_apply_with_message_start user_id=%s",
        callback.from_user.id,
    )
    await callback.answer()
    await state.set_state(ProjectApplyStates.waiting_greeting)
    await callback.message.answer(
        "Напиши сообщение, которое я приложу к заявке.\n\n"
        "Например: кто ты, над чем работаешь и чем хочешь помочь проекту.",
    )


@router.message(ProjectApplyStates.waiting_greeting)
async def proj_req_greeting_message(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
):
    data = await state.get_data()
    project_id = data.get("pending_project_id")
    if not project_id:
        logger.warning(
            "project_apply_greeting_no_project_in_state user_id=%s",
            message.from_user.id,
        )
        await message.answer(
            "Я потерял, к какому проекту прикрепить заявку. "
            "Попробуй ещё раз из ленты.",
        )
        await state.clear()
        return

    greeting = (message.text or "").strip()
    if not greeting:
        await message.answer("Сообщение пустое. Напиши хоть пару слов 🙂")
        return

    logger.info(
        "project_apply_with_message_submit user_id=%s project_id=%s greeting_len=%s",
        message.from_user.id,
        project_id,
        len(greeting),
    )

    await _process_project_connection_request(
        session=session,
        bot=bot,
        from_id=message.from_user.id,
        project_id=project_id,
        source_message=message,
        greeting=greeting,
    )
    await state.clear()
