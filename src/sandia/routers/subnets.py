from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session

from ..audit import log_action
from ..config import Settings, get_settings
from ..config_store import load_live_config
from ..db import get_session
from ..dhcpd import Subnet, serialize
from ..dhcpd.apply import apply_new_config
from ..leases import load_leases
from ..models import User
from ..rendering import render, set_flash
from ..security import require_login, require_role
from ..utilization import subnet_utilization

router = APIRouter()


@router.get("/subnets")
async def list_subnets(
    request: Request,
    user: User = Depends(require_login),
    settings: Settings = Depends(get_settings),
):
    config = load_live_config(settings)
    leases = load_leases(settings.leases_path)
    rows = []
    for subnet in config.subnets:
        used, total = subnet_utilization(subnet, leases)
        rows.append({"subnet": subnet, "used": used, "total": total})
    return render(request, "subnets/list.html", user=user, rows=rows)


@router.get("/subnets/new")
async def new_subnet_form(request: Request, user: User = Depends(require_role("operator"))):
    return render(request, "subnets/form.html", user=user, subnet=None, is_new=True)


@router.post("/subnets/new")
async def create_subnet(
    request: Request,
    user: User = Depends(require_role("operator")),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    network: str = Form(...),
    netmask: str = Form(...),
    range_start: str = Form(...),
    range_end: str = Form(...),
    routers: str = Form(""),
    broadcast_address: str = Form(""),
    domain_name_servers: str = Form(""),
):
    config = load_live_config(settings)
    if config.find_subnet(f"{network}_{netmask}") is not None:
        set_flash(request, "A subnet with that network/netmask already exists.", kind="error")
        return RedirectResponse("/subnets/new", status_code=303)

    subnet = Subnet(network=network, netmask=netmask, body=[])
    subnet.set("range", f"{range_start} {range_end}")
    if routers:
        subnet.set("routers", routers, as_option=True)
    if broadcast_address:
        subnet.set("broadcast-address", broadcast_address, as_option=True)
    if domain_name_servers:
        subnet.set("domain-name-servers", domain_name_servers, as_option=True)
    config.nodes.append(subnet)

    result = await apply_new_config(settings, serialize(config))
    if not result.ok:
        log_action(session, request, user, "subnet_create_failed", result.output, success=False)
        set_flash(request, f"Validation failed ({result.stage}): {result.output}", kind="error")
        return RedirectResponse("/subnets/new", status_code=303)

    log_action(session, request, user, "subnet_create", f"{network}/{netmask}")
    set_flash(request, "Subnet created. Restart isc-dhcp-server to take effect.")
    return RedirectResponse("/subnets", status_code=303)


@router.get("/subnets/{key}/edit")
async def edit_subnet_form(
    key: str,
    request: Request,
    user: User = Depends(require_role("operator")),
    settings: Settings = Depends(get_settings),
):
    config = load_live_config(settings)
    subnet = config.find_subnet(key)
    if subnet is None:
        set_flash(request, "Subnet not found.", kind="error")
        return RedirectResponse("/subnets", status_code=303)
    return render(request, "subnets/form.html", user=user, subnet=subnet, is_new=False)


@router.post("/subnets/{key}/edit")
async def update_subnet(
    key: str,
    request: Request,
    user: User = Depends(require_role("operator")),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    range_start: str = Form(...),
    range_end: str = Form(...),
    routers: str = Form(""),
    broadcast_address: str = Form(""),
    domain_name_servers: str = Form(""),
):
    config = load_live_config(settings)
    subnet = config.find_subnet(key)
    if subnet is None:
        set_flash(request, "Subnet not found.", kind="error")
        return RedirectResponse("/subnets", status_code=303)

    subnet.set("range", f"{range_start} {range_end}")
    if routers:
        subnet.set("routers", routers, as_option=True)
    if broadcast_address:
        subnet.set("broadcast-address", broadcast_address, as_option=True)
    if domain_name_servers:
        subnet.set("domain-name-servers", domain_name_servers, as_option=True)

    result = await apply_new_config(settings, serialize(config))
    if not result.ok:
        log_action(session, request, user, "subnet_update_failed", result.output, success=False)
        set_flash(request, f"Validation failed ({result.stage}): {result.output}", kind="error")
        return RedirectResponse(f"/subnets/{key}/edit", status_code=303)

    log_action(session, request, user, "subnet_update", key)
    set_flash(request, "Subnet updated. Restart isc-dhcp-server to take effect.")
    return RedirectResponse("/subnets", status_code=303)


@router.post("/subnets/{key}/delete")
async def delete_subnet(
    key: str,
    request: Request,
    user: User = Depends(require_role("operator")),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    config = load_live_config(settings)
    if not config.remove_subnet(key):
        set_flash(request, "Subnet not found.", kind="error")
        return RedirectResponse("/subnets", status_code=303)

    result = await apply_new_config(settings, serialize(config))
    if not result.ok:
        log_action(session, request, user, "subnet_delete_failed", result.output, success=False)
        set_flash(request, f"Validation failed ({result.stage}): {result.output}", kind="error")
        return RedirectResponse("/subnets", status_code=303)

    log_action(session, request, user, "subnet_delete", key)
    set_flash(request, "Subnet deleted. Restart isc-dhcp-server to take effect.")
    return RedirectResponse("/subnets", status_code=303)
