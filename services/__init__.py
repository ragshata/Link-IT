# services/__init__.py
from .profiles import (
    ensure_profile,
    get_profile,
    update_profile_data,
    search_profiles_for_user,
)
from .projects import (
    create_user_project,
    get_projects_feed,
    get_project,
)

from .connections import (
    send_connect_request,
    send_project_request,
    send_connection_request,  # backward-compat
    reject_connection_request,
    get_connection_request,
)

__all__ = [
    "ensure_profile",
    "get_profile",
    "update_profile_data",
    "search_profiles_for_user",
    "create_user_project",
    "get_projects_feed",
    "get_project",
    "send_connect_request",
    "send_project_request",
    "send_connection_request",
    "reject_connection_request",
    "get_connection_request",
]
