from fastapi import APIRouter, Depends, Request

from ..config import Settings, get_settings
from ..config_store import load_live_config
from ..device_icons import device_icon_for
from ..leases import load_leases
from ..models import User
from ..rendering import render
from ..security import require_login

router = APIRouter()

MAX_RESULTS_PER_SECTION = 6


@router.get("/search/suggest")
async def search_suggest(
    request: Request,
    user: User = Depends(require_login),
    settings: Settings = Depends(get_settings),
    q: str = "",
):
    query = q.strip()
    if not query:
        return render(request, "search/_suggestions.html", user=user, query="", reservations=[], leases=[], subnets=[])

    needle = query.lower()
    config = load_live_config(settings)

    reservations = [
        {"name": host.name, "fixed_address": host.fixed_address, "icon": device_icon_for(host.name, host.mac)}
        for host in config.all_hosts
        if needle in host.name.lower() or needle in (host.mac or "").lower() or needle in (host.fixed_address or "").lower()
    ][:MAX_RESULTS_PER_SECTION]

    leases = [
        lease
        for lease in load_leases(settings.leases_path)
        if needle in lease.ip.lower() or needle in (lease.mac or "").lower() or needle in (lease.hostname or "").lower()
    ][:MAX_RESULTS_PER_SECTION]

    subnets = [
        subnet for subnet in config.subnets if needle in subnet.network.lower() or needle in subnet.netmask.lower()
    ][:MAX_RESULTS_PER_SECTION]

    return render(
        request,
        "search/_suggestions.html",
        user=user,
        query=query,
        reservations=reservations,
        leases=leases,
        subnets=subnets,
    )
