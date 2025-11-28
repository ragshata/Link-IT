# handlers/browse.py
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from services import search_profiles_for_user
from views import format_profiles_list_text

router = Router()


@router.message(Command("browse"))
async def cmd_browse(message: Message, session: AsyncSession):
    parts = message.text.split()

    if len(parts) < 2:
        await message.answer(
            "Нюхач коллабораций, формат такой:\n"
            "`/browse <goal> [role]`\n\n"
            "Примеры:\n"
            "`/browse mentor backend`\n"
            "`/browse project any`",
            parse_mode="Markdown",
        )
        return

    goal = parts[1].lower()
    role = parts[2].lower() if len(parts) > 2 else None
    if role in ("any", "all", "любой", "любая"):
        role = None

    profiles = await search_profiles_for_user(
        session,
        requester_id=message.from_user.id,
        goal=goal,
        role=role,
        limit=20,
    )

    text = format_profiles_list_text(profiles)
    await message.answer(text)
