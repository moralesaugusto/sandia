from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session

from ..config import Settings, get_settings
from ..config_store import load_live_config
from ..db import get_session
from ..device_icons import device_icon_for
from ..dhcpd import Subnet
from ..dhcpd.backend import get_backend, load_current_leases
from ..dhcpd.extra_options import apply_extra_options, get_extra_options
from ..dhcpd.subnet_interface import get_subnet_interface, set_subnet_interface
from ..diagnostics import diagnose_subnet
from ..i18n import _
from ..ip_map import build_subnet_map, find_cell
from ..models import User
from ..pending_changes import propose_config
from ..rendering import render, set_flash
from ..security import require_login, require_role
from ..utilization import subnet_utilization

router = APIRouter()

# Fields the form manages explicitly - anything else in a subnet's body
# (besides nested host reservations) is shown/edited as free-form "extra
# options" (see dhcpd/extra_options.py).
MANAGED_SUBNET_FIELDS = {
    "range",
    "routers",
    "broadcast-address",
    "domain-name-servers",
    "ntp-servers",
    "next-server",
    "filename",
    "default-lease-time",
    "max-lease-time",
}


def _unquote(value: str | None) -> str:
    return (value or "").strip('"')


def _apply_subnet_fields(
    subnet: Subnet,
    range_start: str,
    range_end: str,
    routers: str,
    broadcast_address: str,
    domain_name_servers: str,
    ntp_servers: str,
    next_server: str,
    boot_filename: str,
    default_lease_time: str,
    max_lease_time: str,
    extra_options: str,
) -> None:
    subnet.set("range", f"{range_start} {range_end}")

    def _set_or_clear(name: str, value: str, as_option: bool = False) -> None:
        if value:
            subnet.set(name, value, as_option=as_option)
        else:
            subnet.body = [n for n in subnet.body if not (hasattr(n, "name") and n.name == name)]

    _set_or_clear("routers", routers, as_option=True)
    _set_or_clear("broadcast-address", broadcast_address, as_option=True)
    _set_or_clear("domain-name-servers", domain_name_servers, as_option=True)
    _set_or_clear("ntp-servers", ntp_servers, as_option=True)
    _set_or_clear("next-server", next_server)
    _set_or_clear("filename", f'"{boot_filename}"' if boot_filename else "")
    _set_or_clear("default-lease-time", default_lease_time)
    _set_or_clear("max-lease-time", max_lease_time)

    subnet.body = apply_extra_options(subnet.body, MANAGED_SUBNET_FIELDS, extra_options)


def _subnet_form_fields(config, subnet: Subnet | None) -> dict:
    if subnet is None:
        return {
            "interface": "",
            "ntp_servers": "",
            "next_server": "",
            "boot_filename": "",
            "default_lease_time": "",
            "max_lease_time": "",
            "extra_options": "",
        }
    return {
        "interface": get_subnet_interface(config, subnet) or "",
        "ntp_servers": subnet.get("ntp-servers") or "",
        "next_server": subnet.get("next-server") or "",
        "boot_filename": _unquote(subnet.get("filename")),
        "default_lease_time": subnet.get("default-lease-time") or "",
        "max_lease_time": subnet.get("max-lease-time") or "",
        "extra_options": get_extra_options(subnet.body, MANAGED_SUBNET_FIELDS),
    }


@router.get("/subnets")
async def list_subnets(
    request: Request,
    user: User = Depends(require_login),
    settings: Settings = Depends(get_settings),
):
    config = load_live_config(settings)
    leases = load_current_leases(settings)
    rows = []
    for subnet in config.subnets:
        used, total = subnet_utilization(subnet, leases)
        rows.append({"subnet": subnet, "used": used, "total": total, "interface": get_subnet_interface(config, subnet)})
    return render(request, "subnets/list.html", user=user, rows=rows)


@router.get("/subnets/new")
async def new_subnet_form(
    request: Request,
    user: User = Depends(require_role("operator")),
    settings: Settings = Depends(get_settings),
):
    config = load_live_config(settings)
    return render(request, "subnets/form.html", user=user, subnet=None, is_new=True, prefill=_subnet_form_fields(config, None))


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
    interface: str = Form(""),
    routers: str = Form(""),
    broadcast_address: str = Form(""),
    domain_name_servers: str = Form(""),
    ntp_servers: str = Form(""),
    next_server: str = Form(""),
    boot_filename: str = Form(""),
    default_lease_time: str = Form(""),
    max_lease_time: str = Form(""),
    extra_options: str = Form(""),
):
    config = load_live_config(settings)
    if config.find_subnet(f"{network}_{netmask}") is not None:
        set_flash(request, _("A subnet with that network/netmask already exists."), kind="error")
        return RedirectResponse("/subnets/new", status_code=303)

    subnet = Subnet(network=network, netmask=netmask, body=[])
    _apply_subnet_fields(
        subnet,
        range_start,
        range_end,
        routers,
        broadcast_address,
        domain_name_servers,
        ntp_servers,
        next_server,
        boot_filename,
        default_lease_time,
        max_lease_time,
        extra_options,
    )
    config.nodes.append(subnet)
    set_subnet_interface(config, subnet, interface.strip())

    detail = f"{network}/{netmask}" + (f" on {interface}" if interface else "")
    return propose_config(
        request, session, settings, user, config, "subnet_create", detail, _("Subnet created. Configuration applied."), "/subnets", "/subnets/new"
    )


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
        set_flash(request, _("Subnet not found."), kind="error")
        return RedirectResponse("/subnets", status_code=303)
    return render(request, "subnets/form.html", user=user, subnet=subnet, is_new=False, prefill=_subnet_form_fields(config, subnet))


@router.post("/subnets/{key}/edit")
async def update_subnet(
    key: str,
    request: Request,
    user: User = Depends(require_role("operator")),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    range_start: str = Form(...),
    range_end: str = Form(...),
    interface: str = Form(""),
    routers: str = Form(""),
    broadcast_address: str = Form(""),
    domain_name_servers: str = Form(""),
    ntp_servers: str = Form(""),
    next_server: str = Form(""),
    boot_filename: str = Form(""),
    default_lease_time: str = Form(""),
    max_lease_time: str = Form(""),
    extra_options: str = Form(""),
):
    config = load_live_config(settings)
    subnet = config.find_subnet(key)
    if subnet is None:
        set_flash(request, _("Subnet not found."), kind="error")
        return RedirectResponse("/subnets", status_code=303)

    _apply_subnet_fields(
        subnet,
        range_start,
        range_end,
        routers,
        broadcast_address,
        domain_name_servers,
        ntp_servers,
        next_server,
        boot_filename,
        default_lease_time,
        max_lease_time,
        extra_options,
    )
    set_subnet_interface(config, subnet, interface.strip())

    return propose_config(
        request, session, settings, user, config, "subnet_update", key, _("Subnet updated. Configuration applied."), "/subnets", f"/subnets/{key}/edit"
    )


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
        set_flash(request, _("Subnet not found."), kind="error")
        return RedirectResponse("/subnets", status_code=303)

    return propose_config(
        request, session, settings, user, config, "subnet_delete", key, _("Subnet deleted. Configuration applied."), "/subnets", "/subnets"
    )


@router.get("/subnets/{key}/map")
async def subnet_map_page(
    key: str,
    request: Request,
    user: User = Depends(require_login),
    settings: Settings = Depends(get_settings),
):
    config = load_live_config(settings)
    subnet = config.find_subnet(key)
    if subnet is None:
        set_flash(request, _("Subnet not found."), kind="error")
        return RedirectResponse("/subnets", status_code=303)

    leases = load_current_leases(settings)
    subnet_map = build_subnet_map(config, subnet, leases)
    return render(request, "subnets/map.html", user=user, subnet=subnet, map=subnet_map)


@router.get("/subnets/{key}/diagnose")
async def subnet_diagnostics(
    key: str,
    request: Request,
    user: User = Depends(require_login),
    settings: Settings = Depends(get_settings),
):
    config = load_live_config(settings)
    subnet = config.find_subnet(key)
    if subnet is None:
        set_flash(request, _("Subnet not found."), kind="error")
        return RedirectResponse("/subnets", status_code=303)

    leases = load_current_leases(settings)
    configured_interfaces = get_backend(settings).listening_interfaces(settings)
    result = diagnose_subnet(config, subnet, leases, configured_interfaces)
    return render(
        request,
        "diagnostics/result.html",
        user=user,
        result=result,
        back_url=f"/subnets/{key}/map",
        back_label=_("Subnet map"),
    )


@router.get("/subnets/{key}/map/{ip}/menu")
async def subnet_map_cell_menu(
    key: str,
    ip: str,
    request: Request,
    user: User = Depends(require_login),
    settings: Settings = Depends(get_settings),
):
    config = load_live_config(settings)
    subnet = config.find_subnet(key)
    if subnet is None:
        return render(request, "subnets/_map_menu.html", user=user, subnet=None, cell=None)

    leases = load_current_leases(settings)
    cell = find_cell(config, subnet, leases, ip)
    icon_name = device_icon_for(cell.host.name, cell.host.mac) if cell and cell.host else None

    deny_host = None
    if cell and cell.status == "denied" and cell.lease and cell.lease.mac:
        deny_host = config.find_host(f"deny-{cell.lease.mac.replace(':', '')}")

    return render(
        request,
        "subnets/_map_menu.html",
        user=user,
        subnet=subnet,
        cell=cell,
        ip=ip,
        icon_name=icon_name,
        deny_host=deny_host,
    )
