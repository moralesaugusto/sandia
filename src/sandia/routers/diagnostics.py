from fastapi import APIRouter, Depends, Request

from ..config import Settings, get_settings
from ..config_store import load_live_config
from ..diagnostics import diagnose_client, diagnose_server, load_dhcp_events
from ..leases import load_leases
from ..models import User
from ..rendering import render
from ..security import require_login

router = APIRouter()


@router.get("/diagnostics")
async def diagnostics_home(
    request: Request,
    user: User = Depends(require_login),
    settings: Settings = Depends(get_settings),
):
    config = load_live_config(settings)
    return render(request, "diagnostics/index.html", user=user, subnets=config.subnets)


@router.get("/diagnostics/server")
async def server_diagnostics(
    request: Request,
    user: User = Depends(require_login),
    settings: Settings = Depends(get_settings),
):
    result = await diagnose_server(settings)
    return render(request, "diagnostics/result.html", user=user, result=result, back_url="/diagnostics", back_label="Diagnostics")


@router.get("/diagnostics/client")
async def client_diagnostics(
    request: Request,
    user: User = Depends(require_login),
    settings: Settings = Depends(get_settings),
    mac: str = "",
    ip: str = "",
    hostname: str = "",
):
    config = load_live_config(settings)
    leases = load_leases(settings.leases_path)
    events, log_unavailable = load_dhcp_events(settings)

    result = diagnose_client(
        config,
        leases,
        events,
        log_unavailable,
        mac=mac or None,
        ip=ip or None,
        hostname=hostname or None,
    )
    return render(request, "diagnostics/result.html", user=user, result=result, back_url="/diagnostics", back_label="Diagnostics")
