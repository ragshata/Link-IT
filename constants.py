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

# Лейблы для кодов стеков (для красивого вывода в профиле)
STACK_LABELS = {
    "backend": "Backend",
    "frontend": "Frontend",
    "fullstack": "Fullstack",
    "mobile": "Mobile",
    "data": "Data",
    "qa": "QA",
    "product": "Product",
    "design": "Design",
    "python": "Python",
    "golang": "Golang",
    "nodejs": "Node.js",
    "java": "Java",
    "php": "PHP",
    "react": "React",
    "vue": "Vue",
    "angular": "Angular",
    "svelte": "Svelte",
    "py_react": "Python + React",
    "node_react": "Node.js + React",
    "php_vue": "PHP + Vue",
}

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
