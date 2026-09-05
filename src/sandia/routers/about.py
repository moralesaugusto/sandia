import platform
import time

import fastapi
import uvicorn
from fastapi import APIRouter, Depends, Request

from .. import __version__
from ..config import Settings, get_settings
from ..models import User
from ..rendering import render
from ..security import require_login

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
    return render(request, "about.html", user=user, info=info)
