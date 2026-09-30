import platform
import time

import fastapi
import uvicorn
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session

from .. import __version__, oui_cache
from ..audit import log_action
from ..config import Settings, get_settings
from ..db import get_session
from ..diagnostics.dhcp_log import MAX_LOG_BYTES
from ..models import User
from ..rendering import render, set_flash
from ..security import require_login, require_role

router = APIRouter()

_started_at = time.monotonic()


def _humanize_uptime(seconds: float) -> str:
    seconds = int(seconds)
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    if minutes or hours or days:
        parts.append(f"{minutes}m")
    parts.append(f"{seconds}s")
    return " ".join(parts)


@router.get("/about")
def about(
    request: Request,
    user: User = Depends(require_login),
    settings: Settings = Depends(get_settings),
):
    info = {
        "version": __version__,
        "uptime": _humanize_uptime(time.monotonic() - _started_at),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "fastapi_version": fastapi.__version__,
        "uvicorn_version": uvicorn.__version__,
        "service_name": settings.service_name,
        "dummy_mode": settings.dummy_data,
        "https_enabled": settings.enable_https,
        "dhcpd_conf_path": str(settings.dhcpd_conf_path),
        "leases_path": str(settings.leases_path),
        "data_dir": str(settings.data_dir),
    }
    log_path = settings.dhcp_log_path
    data_sources = {
        "dhcp_log_path": str(log_path),
        "dhcp_log_size_mb": log_path.stat().st_size / 1_000_000 if log_path.exists() else None,
        "log_window_mb": MAX_LOG_BYTES / 1_000_000,
        "db_path": str(settings.db_path),
    }
    return render(
        request,
        "about.html",
        user=user,
        info=info,
        data_sources=data_sources,
        oui_status=oui_cache.status(settings.data_dir),
    )


@router.post("/about/oui-refresh")
async def refresh_oui_cache(
    request: Request,
    user: User = Depends(require_role("operator")),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    """Kick off a background download of the full IEEE OUI registry. Never
    blocks the request - the download runs in a separate thread, and the
    built-in vendor list keeps working unchanged while it's in progress or
    if it fails."""
    started = oui_cache.start_refresh(settings.data_dir)
    if not started:
        set_flash(request, "An OUI database refresh is already in progress.", kind="error")
        return RedirectResponse("/about", status_code=303)

    log_action(session, request, user, "oui_cache_refresh", "started background refresh")
    set_flash(request, "OUI database refresh started in the background - reload this page in a moment to see progress.")
    return RedirectResponse("/about", status_code=303)
