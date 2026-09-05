from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session

from ..audit import log_action
from ..config import Settings, get_settings
from ..config_store import load_live_config
from ..db import get_session
from ..dhcpd import serialize
from ..dhcpd.apply import apply_new_config, check_config, stage
from ..diff import unified_diff_lines
from ..models import User
from ..rendering import render, set_flash
from ..security import require_login, require_role

router = APIRouter()


@router.get("/config/raw")
async def raw_config_page(
    request: Request,
    user: User = Depends(require_login),
    settings: Settings = Depends(get_settings),
):
    config = load_live_config(settings)
    return render(request, "raw_config.html", user=user, text=serialize(config))


@router.post("/config/raw/validate")
async def raw_config_validate(
    request: Request,
    user: User = Depends(require_role("operator")),
    settings: Settings = Depends(get_settings),
    text: str = Form(...),
):
    await stage(settings, text)
    result = await check_config(settings)
    return render(
        request,
        "raw_config/_validate_result.html",
        user=user,
        ok=result.ok,
        output=(result.stderr or result.stdout).strip(),
    )


@router.post("/config/raw/diff")
async def raw_config_diff(
    request: Request,
    user: User = Depends(require_role("operator")),
    settings: Settings = Depends(get_settings),
    text: str = Form(...),
):
    current = serialize(load_live_config(settings))
    lines = unified_diff_lines(current, text)
    return render(request, "raw_config/_diff_result.html", user=user, lines=lines)


@router.post("/config/raw/apply")
async def raw_config_apply(
    request: Request,
    user: User = Depends(require_role("operator")),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    text: str = Form(...),
):
    result = await apply_new_config(settings, text)
    if not result.ok:
        log_action(session, request, user, "raw_config_apply_failed", result.output, success=False)
        set_flash(request, f"Validation failed ({result.stage}): {result.output}", kind="error")
        return RedirectResponse("/config/raw", status_code=303)

    log_action(session, request, user, "raw_config_apply", "applied raw config edit")
    set_flash(request, "Configuration applied. Restart isc-dhcp-server to take effect.")
    return RedirectResponse("/config/raw", status_code=303)
