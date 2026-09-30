"""Per-session CSRF token, checked on every state-changing request.

Plain forms send it as the `csrf_token` field; htmx and fetch() send it in
the `X-CSRF-Token` header (see base.html).
"""

import secrets

from fastapi import HTTPException, Request, status
from jinja2 import pass_context
from markupsafe import Markup

from .i18n import _

SAFE_METHODS = ("GET", "HEAD", "OPTIONS")
FORM_TYPES = ("application/x-www-form-urlencoded", "multipart/form-data")


def csrf_token(request: Request) -> str:
    token = request.session.get("csrf_token")
    if token is None:
        token = request.session["csrf_token"] = secrets.token_urlsafe(32)
    return token


@pass_context
def template_csrf_token(context) -> str:
    return csrf_token(context["request"])


@pass_context
def csrf_input(context) -> Markup:
    return Markup('<input type="hidden" name="csrf_token" value="{}">').format(csrf_token(context["request"]))


async def verify_csrf(request: Request) -> None:
    if request.method in SAFE_METHODS:
        return
    sent = request.headers.get("x-csrf-token")
    if sent is None and request.headers.get("content-type", "").startswith(FORM_TYPES):
        # Starlette caches the parsed form, so the route's own Form() params still see it.
        sent = (await request.form()).get("csrf_token")
    expected = request.session.get("csrf_token")
    if not expected or not isinstance(sent, str) or not secrets.compare_digest(sent, expected):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_("Invalid or missing CSRF token. Reload the page and try again."),
        )
