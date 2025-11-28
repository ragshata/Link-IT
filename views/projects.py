# views/projects.py
from typing import Sequence

from models import Project
from constants import STACK_LABELS, ROLE_OPTIONS

ROLE_LABELS = {code: label for (label, code) in ROLE_OPTIONS}


def format_project_card(project: Project) -> str:
    stack_label = STACK_LABELS.get(project.stack, project.stack or "—")
    role_label = ROLE_LABELS.get(
        project.looking_for_role, project.looking_for_role or "—"
    )
    level_label = project.level or "—"

    lines: list[str] = []
    lines.append(f"Проект: {project.title}")
    lines.append(f"Стек: {stack_label}")
    lines.append(f"Идея: {project.idea}")
    lines.append(f"Кого ищем: {role_label}")
    lines.append(f"Уровень: {level_label}")
    if project.extra:
        lines.append(f"Ожидания / формат: {project.extra}")
    return "\n".join(lines)


def format_projects_feed(projects: Sequence[Project]) -> str:
    if not projects:
        return "Пока нет проектов. Будь первым, кто опубликует свой — нажми «🆕 Новый проект»."

    blocks: list[str] = ["Проекты, которые сейчас ищут людей:"]
    for p in projects:
        blocks.append(format_project_card(p))

    return "\n\n".join(blocks)
