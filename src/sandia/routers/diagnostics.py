from datetime import datetime

from fastapi import APIRouter, Depends, Request

from ..config import Settings, get_settings
from ..config_store import load_live_config
from ..devices import build_devices
from ..diagnostics import diagnose_client, diagnose_server, load_dhcp_events
from ..diagnostics.dhcp_log import EVENT_KINDS, DhcpEvent
from ..leases import load_lease_history, load_leases
from ..models import User
from ..rendering import render
from ..security import require_login
from ..wall_of_shame import (
    DEFAULT_WINDOW,
    TIME_WINDOWS,
    top_abandoned,
    top_ip_changers,
    top_nak_devices,
)

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


@router.get("/diagnostics/wall-of-shame")
async def wall_of_shame_page(
    request: Request,
    user: User = Depends(require_login),
    settings: Settings = Depends(get_settings),
    window: str = DEFAULT_WINDOW,
):
    if window not in TIME_WINDOWS:
        window = DEFAULT_WINDOW

    config = load_live_config(settings)
    current_leases = load_leases(settings.leases_path)
    lease_history = load_lease_history(settings.leases_path)
    events, log_unavailable = load_dhcp_events(settings)
    devices = build_devices(config, current_leases, lease_history, events)
    now = datetime.now()

    naks = [] if log_unavailable else top_nak_devices(events, devices, now, window)
    ip_changes = top_ip_changers(lease_history, devices, now, window)
    abandoned = top_abandoned(lease_history, devices, config, now, window)

    return render(
        request,
        "diagnostics/wall_of_shame.html",
        user=user,
        window=window,
        naks=naks,
        ip_changes=ip_changes,
        abandoned=abandoned,
        log_unavailable=log_unavailable,
        has_lease_history=bool(lease_history),
    )


# The log tail can hold tens of thousands of events; the table shows the
# newest matches only - narrow with the filters to see older ones.
MAX_EVENT_ROWS = 500


def _filter_events(events: list[DhcpEvent], kind: str, q: str) -> list[DhcpEvent]:
    if kind:
        events = [event for event in events if event.kind == kind]
    if q:
        needle = q.lower()
        events = [
            event
            for event in events
            if needle in event.raw.lower()
            or needle in (event.ip or "")
            or needle in (event.mac or "")
            or needle in (event.hostname or "").lower()
        ]
    return events


def _events_context(settings: Settings, kind: str, q: str) -> dict:
    events, log_unavailable = load_dhcp_events(settings)
    matched = _filter_events(events, kind, q)
    return {
        "events": list(reversed(matched[-MAX_EVENT_ROWS:])),
        "total": len(matched),
        "max_rows": MAX_EVENT_ROWS,
        "log_unavailable": log_unavailable,
        "log_path": settings.dhcp_log_path,
    }


@router.get("/diagnostics/events")
async def event_log_page(
    request: Request,
    user: User = Depends(require_login),
    settings: Settings = Depends(get_settings),
    kind: str = "",
    q: str = "",
):
    return render(
        request,
        "diagnostics/events.html",
        user=user,
        kind=kind,
        q=q,
        kinds=[*EVENT_KINDS, "OTHER"],
        **_events_context(settings, kind, q),
    )


@router.get("/diagnostics/events/table")
async def event_log_table(
    request: Request,
    user: User = Depends(require_login),
    settings: Settings = Depends(get_settings),
    kind: str = "",
    q: str = "",
):
    return render(request, "diagnostics/_events_table.html", user=user, **_events_context(settings, kind, q))


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
