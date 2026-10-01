"""Config changes waiting for review.

Every editor stages its new config text here instead of applying it; the
Review page (routers/review.py) shows its impact and applies it. Each change
is one small JSON file under data_dir, so nothing large goes in the session
cookie and a pending change survives a Sandia restart.
"""

from __future__ import annotations

import json
import re
import secrets
import time
from dataclasses import asdict, dataclass

from fastapi import Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session

from .audit import log_action
from .change_impact import Impact, analyze
from .config import Settings
from .dhcpd import DhcpdConfig, kea
from .dhcpd.apply import render_config_text
from .dhcpd.backend import (
    get_backend,
    live_config_sha,
    live_config_text,
    load_current_leases,
)
from .dhcpd.parser import ParseError
from .i18n import _
from .models import User
from .rendering import set_flash

PENDING_MAX_AGE = 3600

_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")


@dataclass
class PendingChange:
    token: str
    created: float
    username: str
    base_sha: str
    text: str
    action: str
    detail: str
    success_message: str
    return_url: str


def _pending_dir(settings: Settings):
    return settings.data_dir / "pending"


def create(settings: Settings, user: User, text: str, action: str, detail: str, success_message: str, return_url: str) -> str:
    directory = _pending_dir(settings)
    directory.mkdir(parents=True, exist_ok=True)
    now = time.time()
    for old in directory.glob("*.json"):
        if old.stat().st_mtime < now - PENDING_MAX_AGE:
            old.unlink(missing_ok=True)
    change = PendingChange(
        token=secrets.token_urlsafe(18),
        created=now,
        username=user.username,
        base_sha=live_config_sha(settings),
        text=text,
        action=action,
        detail=detail,
        success_message=success_message,
        return_url=return_url,
    )
    (directory / f"{change.token}.json").write_text(json.dumps(asdict(change)))
    return change.token


def load(settings: Settings, token: str, user: User) -> PendingChange | None:
    """The change, if the token is well-formed, not expired, and belongs to
    this user - a review link is not shareable."""
    if not _TOKEN_RE.match(token):
        return None
    path = _pending_dir(settings) / f"{token}.json"
    if not path.is_file():
        return None
    change = PendingChange(**json.loads(path.read_text()))
    if change.username != user.username or change.created < time.time() - PENDING_MAX_AGE:
        return None
    return change


def discard(settings: Settings, token: str) -> None:
    if _TOKEN_RE.match(token):
        (_pending_dir(settings) / f"{token}.json").unlink(missing_ok=True)


def propose_change(
    request: Request, settings: Settings, user: User, text: str, action: str, detail: str, success_message: str, return_url: str
) -> RedirectResponse:
    token = create(settings, user, text, action, detail, success_message, return_url)
    return RedirectResponse(f"/config/review/{token}", status_code=303)


def propose_config(
    request: Request,
    session: Session,
    settings: Settings,
    user: User,
    config: DhcpdConfig,
    action: str,
    detail: str,
    success_message: str,
    return_url: str,
    error_url: str,
) -> RedirectResponse:
    """Render an edited config model and send the user to its Review page.
    An edit that can't be written fails here, before review, as before."""
    try:
        text = render_config_text(settings, config)
    except (ParseError, ValueError) as exc:
        log_action(session, request, user, f"{action}_failed", str(exc), success=False)
        set_flash(request, _("Apply failed ({stage}): {output}", stage="check", output=str(exc)), kind="error")
        return RedirectResponse(error_url, status_code=303)
    return propose_change(request, settings, user, text, action, detail, success_message, return_url)


def _interfaces(settings: Settings, text: str) -> list[str]:
    # Kea's listening interfaces are part of the config text; ISC's live in
    # a separate file a config change doesn't touch.
    backend = get_backend(settings)
    return kea.configured_interfaces(text or "{}") if backend.name == "kea" else backend.listening_interfaces(settings)


def assess(settings: Settings, change: PendingChange) -> Impact:
    """The change's impact against the live config and current leases.
    Raises ParseError when either config can't be read."""
    backend = get_backend(settings)
    live_text = live_config_text(settings) or ""
    old = backend.parse_config(live_text) if live_text else DhcpdConfig()
    new = backend.parse_config(change.text)
    return analyze(old, new, load_current_leases(settings), _interfaces(settings, live_text), _interfaces(settings, change.text))
