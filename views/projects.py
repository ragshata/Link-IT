# views/projects.py
from typing import Sequence

from models import Project
from constants import STACK_LABELS, ROLE_OPTIONS, format_stack_value

from views.safe import html_safe

ROLE_LABELS = {code: label for (label, code) in ROLE_OPTIONS}


def format_project_card(project: Project) -> str:
    """
    Одна карточка проекта (лента + предпросмотр).
    """
    stack_code = getattr(project, "stack", None)
    stack_label = html_safe(format_stack_value(stack_code))

    role_code = getattr(project, "looking_for_role", None)
    role_label = html_safe(ROLE_LABELS.get(role_code, role_code or "—"))

    level_label = html_safe(getattr(project, "level", None) or "—")
    status_label = html_safe(getattr(project, "status", None) or "—")

    # Текущие участники и лимит
    team_limit = getattr(project, "team_limit", None)
    current_members = getattr(project, "current_members", None)
    if current_members is None:
        current_members = 1  # как минимум владелец

    lines: list[str] = []
    lines.append(f"Проект: {html_safe(project.title)}")
    lines.append(f"Статус: {status_label}")
    lines.append(f"Стек: {stack_label}")
    lines.append(f"Идея: {html_safe(project.idea)}")
    lines.append(f"Кого ищем: {role_label}")
    lines.append(f"Уровень: {level_label}")

    needs_now = getattr(project, "needs_now", None)
    if needs_now:
        lines.append(f"Что сейчас нужно: {html_safe(needs_now)}")

    if team_limit is not None:
        free_slots = max(team_limit - current_members, 0)
        lines.append(f"Команда: {current_members}/{team_limit} человек")
        if free_slots > 0:
            lines.append(f"Свободных мест: {free_slots}")
        else:
            lines.append("Свободных мест: нет — команда почти укомплектована")
    else:
        lines.append(f"Команда: {current_members}+ человек")

    extra = getattr(project, "extra", None)
    if extra:
        lines.append(f"Ожидания / формат: {html_safe(extra)}")

    # chat_link намеренно НЕ показываем
    return "\n".join(lines)


def format_projects_feed(projects: Sequence[Project]) -> str:
    """
    Текстовая сводка проектов — сейчас почти не нужна,
    но на неё завязан импорт из views/__init__.py.
    """
    if not projects:
        return (
            "Пока нет проектов. "
            "Будь первым, кто опубликует свой — нажми «🆕 Новый проект»."
        )

    blocks: list[str] = ["Проекты, которые сейчас ищут людей:"]
    for p in projects:
        blocks.append(format_project_card(p))

    return "\n\n".join(blocks)
