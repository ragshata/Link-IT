# constants.py

# Роли в IT
ROLE_OPTIONS = [
    ("Backend", "backend"),
    ("Frontend", "frontend"),
    ("Fullstack", "fullstack"),
    ("Mobile", "mobile"),
    ("Data", "data"),
    ("QA", "qa"),
    ("Product", "product"),
    ("Design", "design"),
]

# Варианты стеков по ролям
STACK_OPTIONS = {
    "backend": [
        ("Python", "python"),
        ("Golang", "golang"),
        ("Node.js", "nodejs"),
        ("Java", "java"),
        ("PHP", "php"),
    ],
    "frontend": [
        ("React", "react"),
        ("Vue", "vue"),
        ("Angular", "angular"),
        ("Svelte", "svelte"),
    ],
    "fullstack": [
        ("Python + React", "py_react"),
        ("Node.js + React", "node_react"),
        ("PHP + Vue", "php_vue"),
    ],
    "mobile": [
        ("Android (Kotlin)", "android_kotlin"),
        ("iOS (Swift)", "ios_swift"),
        ("Flutter", "flutter"),
        ("React Native", "react_native"),
    ],
    "data": [
        ("Python DS", "python_ds"),
        ("Spark", "spark"),
        ("SQL/BI", "sql_bi"),
    ],
    "qa": [
        ("Manual QA", "qa_manual"),
        ("Automation (Python)", "qa_auto_py"),
        ("Automation (JS)", "qa_auto_js"),
    ],
    "product": [
        ("Product Manager", "product_manager"),
        ("Product Analyst", "product_analyst"),
    ],
    "design": [
        ("UI/UX", "uiux"),
        ("Product design", "product_design"),
    ],
}

# ---------------------------------------------------------------------
# STACK_LABELS (автоматически)
# ---------------------------------------------------------------------
# Вместо ручного словаря (который вы 100% забудете обновить),
# генерируем лейблы из STACK_OPTIONS.
# Плюс оверрайды на "группы" и общие коды.
_STACK_LABEL_OVERRIDES: dict[str, str] = {
    "backend": "Backend",
    "frontend": "Frontend",
    "fullstack": "Fullstack",
    "mobile": "Mobile",
    "data": "Data",
    "qa": "QA",
    "product": "Product",
    "design": "Design",
    "other": "Другое",
}


def build_stack_labels() -> dict[str, str]:
    labels: dict[str, str] = dict(_STACK_LABEL_OVERRIDES)
    for opts in STACK_OPTIONS.values():
        for label, code in opts:
            labels.setdefault(code, label)
    return labels


STACK_LABELS = build_stack_labels()


def format_stack_value(stack_raw: str | None) -> str:
    """
    Делает стек человеко-читаемым.
    Поддерживает составные значения, которые вы храните строкой, например:
      - "python"
      - "python, nodejs"
      - "python, react; FastAPI"
      - "py_react; docker"
    Правила:
      - разделитель групп: ';'
      - разделитель элементов внутри группы: ','
    """
    if not stack_raw:
        return "—"

    # Если пришёл ровно один код, отдадим красиво
    if stack_raw in STACK_LABELS:
        return STACK_LABELS[stack_raw]

    parts: list[str] = []
    for group in stack_raw.split(";"):
        group = group.strip()
        if not group:
            continue

        tokens = [t.strip() for t in group.split(",") if t.strip()]
        if not tokens:
            continue

        mapped = [STACK_LABELS.get(t, t) for t in tokens]
        parts.append(", ".join(mapped))

    return (
        "; ".join(parts) if parts else (STACK_LABELS.get(stack_raw, stack_raw) or "—")
    )


# Популярные фреймворки по языкам/стекам
# Для fullstack-комбинаций даём сразу набор backend+frontend фреймворков
FRAMEWORK_OPTIONS = {
    # backend
    "python": [
        ("Django", "django"),
        ("FastAPI", "fastapi"),
        ("Flask", "flask"),
    ],
    "golang": [
        ("Gin", "gin"),
        ("Echo", "echo"),
        ("Fiber", "fiber"),
    ],
    "nodejs": [
        ("Express", "express"),
        ("NestJS", "nestjs"),
    ],
    "java": [
        ("Spring", "spring"),
        ("Quarkus", "quarkus"),
    ],
    "php": [
        ("Laravel", "laravel"),
        ("Symfony", "symfony"),
    ],
    # frontend
    "react": [
        ("React", "react"),
        ("Next.js", "nextjs"),
    ],
    "vue": [
        ("Vue", "vue"),
        ("Nuxt", "nuxt"),
    ],
    # fullstack-комбо
    "py_react": [
        ("Django", "django"),
        ("FastAPI", "fastapi"),
        ("Flask", "flask"),
        ("React", "react"),
        ("Next.js", "nextjs"),
    ],
    "node_react": [
        ("Express", "express"),
        ("NestJS", "nestjs"),
        ("React", "react"),
        ("Next.js", "nextjs"),
    ],
    "php_vue": [
        ("Laravel", "laravel"),
        ("Symfony", "symfony"),
        ("Vue", "vue"),
        ("Nuxt", "nuxt"),
    ],
}

# Общие навыки — для инлайн-кнопок
SKILL_OPTIONS = [
    ("Git", "git"),
    ("SQL", "sql"),
    ("Docker", "docker"),
    ("Linux", "linux"),
    ("CI/CD", "cicd"),
    ("Английский B1+", "english"),
    ("Другое", "other"),
    ("Готово", "done"),
]

# Цели пользователя
GOAL_OPTIONS = [
    ("Найти ментора", "find_mentor"),
    ("Стать ментором", "be_mentor"),
    ("Найти напарника", "find_teammate"),
    ("Найти проект", "find_project"),
    ("Найти джуна/помощника", "find_junior"),
]

# 🔥 Статусы проекта (жизненный цикл)
PROJECT_STATUS_OPTIONS = [
    ("💡 Идея", "idea"),
    ("🧪 Прототип", "prototype"),
    ("🚧 В работе", "in_progress"),
    ("🧊 Заморожен", "frozen"),
    ("🚀 Запущен", "launched"),
]

PROJECT_STATUS_LABELS = {
    "idea": "💡 Идея",
    "prototype": "🧪 Прототип",
    "in_progress": "🚧 В работе",
    "frozen": "🧊 Заморожен",
    "launched": "🚀 Запущен",
}
