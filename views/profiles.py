# views/profiles.py
from typing import Sequence

from models import Profile
from constants import STACK_LABELS, ROLE_OPTIONS, GOAL_OPTIONS
from views.safe import html_safe


ROLE_LABELS = {code: label for (label, code) in ROLE_OPTIONS}
GOAL_LABELS = {code: label for (label, code) in GOAL_OPTIONS}


def format_profile_text(
    profile: Profile,
    *,
    fallback_username: str | None = None,
) -> str:
    """
    Полный вид профиля — для /profile, тут МОЖНО показывать @username.
    В ЛЕНТЕ ЭТО НЕ ИСПОЛЬЗУЕМ.
    """
    username = html_safe(profile.username or fallback_username, default="без username")

    stack_raw = profile.stack
    stack_label = html_safe(STACK_LABELS.get(stack_raw, stack_raw or "—"))

    role_label = html_safe(ROLE_LABELS.get(profile.role, profile.role or "—"))
    goals_label = html_safe(GOAL_LABELS.get(profile.goals, profile.goals or "—"))

    lines: list[str] = []
    lines.append(f"Профиль @{username}:")
    lines.append(f"Имя: {html_safe(profile.first_name)}")
    lines.append(f"Роль: {role_label}")
    lines.append(f"Язык/стек: {stack_label}")
    lines.append(f"Фреймворк: {html_safe(profile.framework)}")
    lines.append(f"Навыки: {html_safe(profile.skills)}")
    lines.append(f"Цели: {goals_label}")
    lines.append(f"О себе: {html_safe(profile.about)}")
    return "\n".join(lines)


def format_profile_public(profile: Profile) -> str:
    """
    Публичный вид профиля — БЕЗ username и любых контактов.
    Это используется в:
    - ленте разработчиков,
    - заявках на общение.
    """
    stack_raw = profile.stack
    stack_label = html_safe(STACK_LABELS.get(stack_raw, stack_raw or "—"))

    role_label = html_safe(ROLE_LABELS.get(profile.role, profile.role or "—"))
    goals_label = html_safe(GOAL_LABELS.get(profile.goals, profile.goals or "—"))

    lines: list[str] = []
    lines.append("Профиль разработчика:")
    lines.append(f"Имя: {html_safe(profile.first_name)}")
    lines.append(f"Роль: {role_label}")
    lines.append(f"Язык/стек: {stack_label}")
    lines.append(f"Фреймворк: {html_safe(profile.framework)}")
    lines.append(f"Навыки: {html_safe(profile.skills)}")
    lines.append(f"Цели: {goals_label}")
    lines.append(f"О себе: {html_safe(profile.about)}")
    return "\n".join(lines)


def format_profiles_list_text(
    profiles: Sequence[Profile],
) -> str:
    """
    Текстовая выдача списка профилей (например, /browse).
    Тоже без username, чтобы не светить контакты до матча.
    """
    if not profiles:
        return "Пока никого не нашлось под такие параметры. Попробуй изменить фильтры."

    blocks: list[str] = []

    for p in profiles:
        stack_raw = p.stack
        stack_label = html_safe(STACK_LABELS.get(stack_raw, stack_raw or "—"))

        role_label = html_safe(ROLE_LABELS.get(p.role, p.role or "—"))
        goals_label = html_safe(GOAL_LABELS.get(p.goals, p.goals or "—"))

        lines = [
            "Профиль разработчика:",
            f"Имя: {html_safe(p.first_name)}",
            f"Роль: {role_label}",
            f"Стек: {stack_label}",
            f"Фреймворк: {html_safe(p.framework)}",
            f"Навыки: {html_safe(p.skills)}",
            f"Цели: {goals_label}",
            f"О себе: {html_safe(p.about)}",
        ]
        blocks.append("\n".join(lines))

    return "\n\n────────────\n\n".join(blocks)
