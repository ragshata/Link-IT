# handlers/projects/__init__.py

from aiogram import Router

from .create import router as create_router, start_project_registration
from .feed import router as feed_router
from .apply import router as apply_router


projects_router = Router()
projects_router.include_router(create_router)
projects_router.include_router(feed_router)
projects_router.include_router(apply_router)

__all__ = [
    "projects_router",
    "start_project_registration",
]
