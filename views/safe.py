# views/safe.py
from __future__ import annotations

from html import escape


def html_safe(value, default: str = "—") -> str:
    """
    Экранирует строку для ParseMode.HTML.
    - None/пустое -> default
    - иначе -> html.escape(..., quote=True)
    """
    if value is None:
        return default

    s = str(value)
    s = s.strip()
    if not s:
        return default

    return escape(s, quote=True)
