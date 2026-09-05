from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session

from ..audit import log_action
from ..config import Settings, get_settings
from ..config_store import load_live_config
from ..csv_export import csv_response
from ..db import get_session
from ..device_icons import device_icon_for
from ..dhcpd import Host, serialize
from ..dhcpd.apply import apply_new_config
from ..dhcpd.extra_options import apply_extra_options, get_extra_options
from ..models import User
from ..rendering import render, set_flash
from ..security import require_login, require_role
from ..vendors import lookup_vendor

router = APIRouter()

# Fields the form manages explicitly - anything else in a host's body is
# shown/edited as free-form "extra options" (see dhcpd/extra_options.py).
MANAGED_HOST_FIELDS = {"hardware", "fixed-address", "host-name", "next-server", "filename", "deny"}


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


def _unquote(value: str | None) -> str:
    return (value or "").strip('"')


def _apply_host_fields(
    host: Host,
    mac: str,
    fixed_address: str,
    client_hostname: str,
    next_server: str,
    boot_filename: str,
    extra_options: str,
) -> None:
    host.set_mac(mac)
    host.set_fixed_address(fixed_address)

    if client_hostname:
        host.set("host-name", f'"{client_hostname}"', as_option=True)
    else:
        host.body = [n for n in host.body if not (hasattr(n, "name") and n.name == "host-name")]

    if next_server:
        host.set("next-server", next_server)
    else:
        host.body = [n for n in host.body if not (hasattr(n, "name") and n.name == "next-server")]

    if boot_filename:
        host.set("filename", f'"{boot_filename}"')
    else:
        host.body = [n for n in host.body if not (hasattr(n, "name") and n.name == "filename")]

    host.body = apply_extra_options(host.body, MANAGED_HOST_FIELDS, extra_options)


def _host_form_fields(host: Host | None) -> dict:
    if host is None:
        return {"client_hostname": "", "next_server": "", "boot_filename": "", "extra_options": ""}
    return {
        "client_hostname": _unquote(host.get("host-name")),
        "next_server": host.get("next-server") or "",
        "boot_filename": _unquote(host.get("filename")),
        "extra_options": get_extra_options(host.body, MANAGED_HOST_FIELDS),
    }


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
    rows = [
        {"host": host, "subnet": host_subnet.get(host.name), "icon": device_icon_for(host.name, host.mac)}
        for host in hosts
    ]
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
    prefill = {"name": hostname, "mac": mac, "fixed_address": ip, "subnet_key": "", **_host_form_fields(None)}
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
    client_hostname: str = Form(""),
    next_server: str = Form(""),
    boot_filename: str = Form(""),
    extra_options: str = Form(""),
):
    config = load_live_config(settings)
    if config.find_host(name) is not None:
        set_flash(request, "A reservation with that name already exists.", kind="error")
        return RedirectResponse("/reservations/new", status_code=303)

    host = Host(name=name, body=[])
    _apply_host_fields(host, mac, fixed_address, client_hostname, next_server, boot_filename, extra_options)

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
    return render(
        request,
        "reservations/form.html",
        user=user,
        host=host,
        is_new=False,
        subnets=config.subnets,
        prefill=_host_form_fields(host),
    )


@router.post("/reservations/{name}/edit")
async def update_reservation(
    name: str,
    request: Request,
    user: User = Depends(require_role("operator")),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    mac: str = Form(...),
    fixed_address: str = Form(...),
    client_hostname: str = Form(""),
    next_server: str = Form(""),
    boot_filename: str = Form(""),
    extra_options: str = Form(""),
):
    config = load_live_config(settings)
    host = config.find_host(name)
    if host is None:
        set_flash(request, "Reservation not found.", kind="error")
        return RedirectResponse("/reservations", status_code=303)

    _apply_host_fields(host, mac, fixed_address, client_hostname, next_server, boot_filename, extra_options)

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


@router.post("/reservations/bulk-delete")
async def bulk_delete_reservations(
    request: Request,
    user: User = Depends(require_role("operator")),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    names: list[str] = Form(default=[]),
):
    if not names:
        set_flash(request, "No reservations selected.", kind="error")
        return RedirectResponse("/reservations", status_code=303)

    config = load_live_config(settings)
    removed = [name for name in names if config.remove_host(name)]
    if not removed:
        set_flash(request, "None of the selected reservations were found.", kind="error")
        return RedirectResponse("/reservations", status_code=303)

    result = await apply_new_config(settings, serialize(config))
    if not result.ok:
        log_action(session, request, user, "reservation_bulk_delete_failed", result.output, success=False)
        set_flash(request, f"Validation failed ({result.stage}): {result.output}", kind="error")
        return RedirectResponse("/reservations", status_code=303)

    log_action(session, request, user, "reservation_bulk_delete", ", ".join(removed))
    set_flash(request, f"Deleted {len(removed)} reservation(s). Restart isc-dhcp-server to take effect.")
    return RedirectResponse("/reservations", status_code=303)
