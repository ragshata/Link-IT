# views/__init__.py
from .profiles import (
    format_profile_text,
    format_profile_public,
    format_profiles_list_text,
)
from .projects import (
    format_project_card,
    format_projects_feed,
)
from .safe import html_safe


__all__ = [
    "format_profile_text",
    "format_profile_public",
    "format_profiles_list_text",
    "format_project_card",
    "format_projects_feed",
    "html_safe",
]
