from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session

from ..audit import log_action
from ..config import Settings, get_settings
from ..config_store import load_live_config
from ..csv_export import csv_response
from ..db import get_session
from ..dhcpd import Host, serialize
from ..dhcpd.apply import apply_new_config
from ..models import User
from ..rendering import render, set_flash
from ..security import require_login, require_role
from ..vendors import lookup_vendor

router = APIRouter()


def _host_subnet_map(config) -> dict:
    host_subnet = {}
    for subnet in config.subnets:
        for host in subnet.hosts:
            host_subnet[host.name] = subnet
    return host_subnet


def _filter_hosts(hosts: list[Host], q: str) -> list[Host]:
    if not q:
        return hosts
    needle = q.lower()
    return [
        host
        for host in hosts
        if needle in host.name.lower()
        or needle in (host.mac or "").lower()
        or needle in (host.fixed_address or "").lower()
    ]


@router.get("/reservations")
async def list_reservations(
    request: Request,
    user: User = Depends(require_login),
    settings: Settings = Depends(get_settings),
    q: str = "",
):
    config = load_live_config(settings)
    host_subnet = _host_subnet_map(config)
    hosts = _filter_hosts(config.all_hosts, q)
    rows = [{"host": host, "subnet": host_subnet.get(host.name)} for host in hosts]
    return render(request, "reservations/list.html", user=user, rows=rows, q=q)


@router.get("/reservations/export.csv")
async def export_reservations_csv(
    user: User = Depends(require_login),
    settings: Settings = Depends(get_settings),
    q: str = "",
):
    config = load_live_config(settings)
    host_subnet = _host_subnet_map(config)
    hosts = _filter_hosts(config.all_hosts, q)
    rows = [
        [
            host.name,
            host.mac or "",
            lookup_vendor(host.mac) or "",
            host.fixed_address or "",
            f"{host_subnet[host.name].network}/{host_subnet[host.name].netmask}" if host.name in host_subnet else "global",
        ]
        for host in hosts
    ]
    return csv_response("reservations.csv", ["name", "mac", "vendor", "fixed_address", "subnet"], rows)


@router.get("/reservations/new")
async def new_reservation_form(
    request: Request,
    user: User = Depends(require_role("operator")),
    settings: Settings = Depends(get_settings),
    mac: str = "",
    ip: str = "",
    hostname: str = "",
):
    config = load_live_config(settings)
    prefill = {"name": hostname, "mac": mac, "fixed_address": ip, "subnet_key": ""}
    return render(
        request,
        "reservations/form.html",
        user=user,
        host=None,
        is_new=True,
        subnets=config.subnets,
        prefill=prefill,
    )


@router.post("/reservations/new")
async def create_reservation(
    request: Request,
    user: User = Depends(require_role("operator")),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    name: str = Form(...),
    mac: str = Form(...),
    fixed_address: str = Form(...),
    subnet_key: str = Form(""),
):
    config = load_live_config(settings)
    if config.find_host(name) is not None:
        set_flash(request, "A reservation with that name already exists.", kind="error")
        return RedirectResponse("/reservations/new", status_code=303)

    host = Host(name=name, body=[])
    host.set_mac(mac)
    host.set_fixed_address(fixed_address)

    if subnet_key:
        subnet = config.find_subnet(subnet_key)
        if subnet is None:
            set_flash(request, "Selected subnet not found.", kind="error")
            return RedirectResponse("/reservations/new", status_code=303)
        subnet.body.append(host)
    else:
        config.nodes.append(host)

    result = await apply_new_config(settings, serialize(config))
    if not result.ok:
        log_action(session, request, user, "reservation_create_failed", result.output, success=False)
        set_flash(request, f"Validation failed ({result.stage}): {result.output}", kind="error")
        return RedirectResponse("/reservations/new", status_code=303)

    log_action(session, request, user, "reservation_create", f"{name} ({mac} -> {fixed_address})")
    set_flash(request, "Reservation created. Restart isc-dhcp-server to take effect.")
    return RedirectResponse("/reservations", status_code=303)


@router.get("/reservations/{name}/edit")
async def edit_reservation_form(
    name: str,
    request: Request,
    user: User = Depends(require_role("operator")),
    settings: Settings = Depends(get_settings),
):
    config = load_live_config(settings)
    host = config.find_host(name)
    if host is None:
        set_flash(request, "Reservation not found.", kind="error")
        return RedirectResponse("/reservations", status_code=303)
    return render(request, "reservations/form.html", user=user, host=host, is_new=False, subnets=config.subnets, prefill=None)


@router.post("/reservations/{name}/edit")
async def update_reservation(
    name: str,
    request: Request,
    user: User = Depends(require_role("operator")),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    mac: str = Form(...),
    fixed_address: str = Form(...),
):
    config = load_live_config(settings)
    host = config.find_host(name)
    if host is None:
        set_flash(request, "Reservation not found.", kind="error")
        return RedirectResponse("/reservations", status_code=303)

    host.set_mac(mac)
    host.set_fixed_address(fixed_address)

    result = await apply_new_config(settings, serialize(config))
    if not result.ok:
        log_action(session, request, user, "reservation_update_failed", result.output, success=False)
        set_flash(request, f"Validation failed ({result.stage}): {result.output}", kind="error")
        return RedirectResponse(f"/reservations/{name}/edit", status_code=303)

    log_action(session, request, user, "reservation_update", name)
    set_flash(request, "Reservation updated. Restart isc-dhcp-server to take effect.")
    return RedirectResponse("/reservations", status_code=303)


@router.post("/reservations/{name}/delete")
async def delete_reservation(
    name: str,
    request: Request,
    user: User = Depends(require_role("operator")),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    config = load_live_config(settings)
    if not config.remove_host(name):
        set_flash(request, "Reservation not found.", kind="error")
        return RedirectResponse("/reservations", status_code=303)

    result = await apply_new_config(settings, serialize(config))
    if not result.ok:
        log_action(session, request, user, "reservation_delete_failed", result.output, success=False)
        set_flash(request, f"Validation failed ({result.stage}): {result.output}", kind="error")
        return RedirectResponse("/reservations", status_code=303)

    log_action(session, request, user, "reservation_delete", name)
    set_flash(request, "Reservation deleted. Restart isc-dhcp-server to take effect.")
    return RedirectResponse("/reservations", status_code=303)
