# views/profiles.py
from typing import Sequence

from models import Profile
from constants import STACK_LABELS, ROLE_OPTIONS, GOAL_OPTIONS


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
    username = profile.username or fallback_username or "без username"

    stack_raw = profile.stack
    stack_label = STACK_LABELS.get(stack_raw, stack_raw or "—")

    role_label = ROLE_LABELS.get(profile.role, profile.role or "—")
    goals_label = GOAL_LABELS.get(profile.goals, profile.goals or "—")

    lines: list[str] = []
    lines.append(f"Профиль @{username}:")
    lines.append(f"Имя: {profile.first_name or '—'}")
    lines.append(f"Роль: {role_label}")
    lines.append(f"Язык/стек: {stack_label}")
    lines.append(f"Фреймворк: {profile.framework or '—'}")
    lines.append(f"Навыки: {profile.skills or '—'}")
    lines.append(f"Цели: {goals_label}")
    lines.append(f"О себе: {profile.about or '—'}")
    return "\n".join(lines)


def format_profile_public(profile: Profile) -> str:
    """
    Публичный вид профиля — БЕЗ username и любых контактов.
    Это используется в:
    - ленте разработчиков,
    - заявках на общение.
    """
    stack_raw = profile.stack
    stack_label = STACK_LABELS.get(stack_raw, stack_raw or "—")

    role_label = ROLE_LABELS.get(profile.role, profile.role or "—")
    goals_label = GOAL_LABELS.get(profile.goals, profile.goals or "—")

    lines: list[str] = []
    lines.append("Профиль разработчика:")
    lines.append(f"Имя: {profile.first_name or '—'}")
    lines.append(f"Роль: {role_label}")
    lines.append(f"Язык/стек: {stack_label}")
    lines.append(f"Фреймворк: {profile.framework or '—'}")
    lines.append(f"Навыки: {profile.skills or '—'}")
    lines.append(f"Цели: {goals_label}")
    lines.append(f"О себе: {profile.about or '—'}")
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
        stack_label = STACK_LABELS.get(stack_raw, stack_raw or "—")

        role_label = ROLE_LABELS.get(p.role, p.role or "—")
        goals_label = GOAL_LABELS.get(p.goals, p.goals or "—")

        lines = [
            "Профиль разработчика:",
            f"Имя: {p.first_name or '—'}",
            f"Роль: {role_label}",
            f"Стек: {stack_label}",
            f"Фреймворк: {p.framework or '—'}",
            f"Навыки: {p.skills or '—'}",
            f"Цели: {goals_label}",
            f"О себе: {p.about or '—'}",
        ]
        blocks.append("\n".join(lines))

    return "\n\n────────────\n\n".join(blocks)
