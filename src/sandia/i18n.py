"""English/Spanish UI text.

English source strings are the catalog keys, so English needs no catalog
and a missing Spanish entry falls back to English. The current language
lives in a contextvar set once per request by LanguageMiddleware, so `_()`
works the same in templates, routers and diagnostics code.
"""

from contextvars import ContextVar

from markupsafe import Markup

from .i18n_es import ES

LANGUAGES = {"en": "English", "es": "Español"}
DEFAULT_LANGUAGE = "en"

_lang: ContextVar[str] = ContextVar("lang", default=DEFAULT_LANGUAGE)


def current_language() -> str:
    return _lang.get()


def N_(text: str) -> str:
    """Marks a string for translation where it's defined (e.g. a module-level
    label table), to be passed through _() when displayed."""
    return text


def _translate(text: str) -> str:
    return ES.get(text, text) if _lang.get() == "es" else text


def _(text: str, **kwargs) -> str:
    text = _translate(text)
    return text.format(**kwargs) if kwargs else text


def template_gettext(text: str, **kwargs) -> Markup:
    """_() for Jinja templates. Catalog text is trusted and keeps its quotes
    as-is (only &, <, > are escaped); the kwargs are data and get fully
    escaped by Markup.format()."""
    text = _translate(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return Markup(text).format(**kwargs) if kwargs else Markup(text)


class LanguageMiddleware:
    """Pure ASGI middleware; must sit inside SessionMiddleware so the
    session is already decoded."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        lang = scope["session"].get("lang", DEFAULT_LANGUAGE)
        token = _lang.set(lang if lang in LANGUAGES else DEFAULT_LANGUAGE)
        try:
            await self.app(scope, receive, send)
        finally:
            _lang.reset(token)
