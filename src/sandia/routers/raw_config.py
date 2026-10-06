from fastapi import APIRouter, Depends, Form, Request

from ..config import Settings, get_settings
from ..dhcpd.apply import validate_text
from ..dhcpd.backend import get_backend, live_config_text
from ..diff import unified_diff_lines
from ..i18n import _
from ..models import User
from ..pending_changes import propose_change
from ..rendering import render
from ..security import require_login, require_role

router = APIRouter()


def _current_text(settings: Settings) -> str:
    return get_backend(settings).raw_text(live_config_text(settings) or "")


@router.get("/config/raw")
async def raw_config_page(
    request: Request,
    user: User = Depends(require_login),
    settings: Settings = Depends(get_settings),
):
    return render(request, "raw_config.html", user=user, text=_current_text(settings))


@router.post("/config/raw/validate")
async def raw_config_validate(
    request: Request,
    user: User = Depends(require_role("operator")),
    settings: Settings = Depends(get_settings),
    text: str = Form(...),
):
    result = await validate_text(settings, text)
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
    current = _current_text(settings)
    lines = unified_diff_lines(current, text, get_backend(settings).backup_prefix)
    return render(request, "raw_config/_diff_result.html", user=user, lines=lines)


@router.post("/config/raw/apply")
async def raw_config_apply(
    request: Request,
    user: User = Depends(require_role("operator")),
    settings: Settings = Depends(get_settings),
    text: str = Form(...),
):
    message = _("Configuration applied. {service} restarted.", service=get_backend(settings).label)
    return propose_change(request, settings, user, text, "raw_config_apply", "applied raw config edit", message, "/config/raw")
