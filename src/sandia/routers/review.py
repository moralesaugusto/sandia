from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session

from ..audit import log_action
from ..config import Settings, get_settings
from ..db import get_session
from ..dhcpd import ParseError
from ..dhcpd.apply import apply_new_config, config_lock, validate_text
from ..dhcpd.backend import (
    get_backend,
    live_config_sha,
    live_config_text,
)
from ..diff import unified_diff_lines
from ..i18n import _
from ..models import User
from ..pending_changes import PendingChange, assess, discard, load
from ..rendering import render, set_flash
from ..rollback_window import clear_apply, record_apply, rollback_offer
from ..security import require_role

router = APIRouter()


def _pending(settings: Settings, token: str, user: User) -> PendingChange:
    change = load(settings, token, user)
    if change is None:
        raise HTTPException(status_code=404, detail=_("This change is no longer pending. Make the edit again."))
    return change


def _local_url(url: str) -> str:
    return url if url.startswith("/") and not url.startswith("//") else "/"


@router.get("/config/review/{token}")
async def review_page(
    token: str,
    request: Request,
    user: User = Depends(require_role("operator")),
    settings: Settings = Depends(get_settings),
):
    change = _pending(settings, token, user)
    backend = get_backend(settings)
    live_text = live_config_text(settings) or ""

    checked = await validate_text(settings, change.text)

    impact, parse_error = None, None
    try:
        impact = assess(settings, change)
    except ParseError as exc:
        parse_error = str(exc)

    return render(
        request,
        "config/review.html",
        user=user,
        change=change,
        impact=impact,
        parse_error=parse_error,
        check_ok=checked.ok,
        check_output=(checked.stderr or checked.stdout).strip(),
        stale=live_config_sha(settings) != change.base_sha,
        lines=unified_diff_lines(backend.raw_text(live_text) if live_text else "", change.text, backend.backup_prefix),
    )


@router.post("/config/review/{token}/apply")
async def review_apply(
    token: str,
    request: Request,
    user: User = Depends(require_role("operator")),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    change = _pending(settings, token, user)
    discard(settings, token)
    # Held from the stale check to record_apply, so no other apply or
    # rollback can change the config in between (SEC-2026-02, fixed).
    async with config_lock:
        if live_config_sha(settings) != change.base_sha:
            set_flash(request, _("The configuration changed after this edit was prepared, so it was not applied. Make the edit again."), kind="error")
            return RedirectResponse(change.return_url, status_code=303)

        result = await apply_new_config(settings, change.text)
        if not result.ok:
            log_action(session, request, user, f"{change.action}_failed", result.output, success=False)
            set_flash(request, _("Apply failed ({stage}): {output}", stage=result.stage, output=result.output), kind="error")
            return RedirectResponse(change.return_url, status_code=303)

        if result.backup is not None:
            record_apply(settings, result.backup.name, user.username, change.action)
    log_action(session, request, user, change.action, change.detail)
    set_flash(request, change.success_message)
    return RedirectResponse(change.return_url, status_code=303)


@router.post("/config/review/{token}/cancel")
async def review_cancel(
    token: str,
    request: Request,
    user: User = Depends(require_role("operator")),
    settings: Settings = Depends(get_settings),
):
    change = _pending(settings, token, user)
    discard(settings, token)
    set_flash(request, _("Change discarded. Nothing was applied."))
    return RedirectResponse(change.return_url, status_code=303)


@router.post("/config/rollback")
async def rollback_last_apply(
    request: Request,
    user: User = Depends(require_role("operator")),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    next_url: str = Form("/"),
):
    # The offer is checked and consumed under the lock, so two rollbacks (or
    # a rollback racing an apply) can't both act on it (SEC-2026-02, fixed).
    async with config_lock:
        offer = rollback_offer(settings)
        if offer is None:
            set_flash(request, _("There is no recent change to roll back."), kind="error")
            return RedirectResponse(_local_url(next_url), status_code=303)

        result = await apply_new_config(settings, (settings.backup_dir / offer.backup).read_text())
        if not result.ok:
            log_action(session, request, user, "config_rollback_failed", result.output, success=False)
            set_flash(request, _("Rollback failed ({stage}): {output}", stage=result.stage, output=result.output), kind="error")
            return RedirectResponse(_local_url(next_url), status_code=303)

        clear_apply(settings)
    log_action(session, request, user, "config_rollback", f"{offer.action} -> {offer.backup}")
    set_flash(request, _("Rolled back to the configuration before the last change ({backup}).", backup=offer.backup))
    return RedirectResponse(_local_url(next_url), status_code=303)


@router.post("/config/rollback/keep")
async def keep_last_apply(
    request: Request,
    user: User = Depends(require_role("operator")),
    settings: Settings = Depends(get_settings),
    next_url: str = Form("/"),
):
    clear_apply(settings)
    return RedirectResponse(_local_url(next_url), status_code=303)
