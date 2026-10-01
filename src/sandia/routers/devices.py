
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session

from ..audit import log_action
from ..config import Settings, get_settings
from ..config_store import load_live_config
from ..csv_export import csv_response
from ..db import get_session
from ..devices import (
    STATUS_LABELS,
    build_devices,
    filter_devices,
    find_device,
    sort_devices,
)
from ..dhcpd.backend import get_backend, load_current_leases, load_lease_records
from ..diagnostics import diagnose_client, load_dhcp_events
from ..i18n import N_, _
from ..ip_map import build_subnet_map, denied_macs, next_available_ip
from ..models import User
from ..rendering import render, set_flash
from ..security import require_login, require_role

router = APIRouter()

STATUS_OPTIONS = [("", N_("All statuses"))] + [(status.value, label) for status, label in STATUS_LABELS.items()]


def _load_devices(settings: Settings):
    config = load_live_config(settings)
    current_leases = load_current_leases(settings)
    lease_history = load_lease_records(settings)
    events, log_unavailable = load_dhcp_events(settings)
    devices = build_devices(config, current_leases, lease_history, events)
    return config, devices, current_leases, events, log_unavailable


def _apply_filters(devices, q, status, reservation, lease, subnet_key, vendor, sort):
    filtered = filter_devices(devices, q=q, status=status, reservation=reservation, lease=lease, subnet_key=subnet_key, vendor=vendor)
    return sort_devices(filtered, sort=sort)


@router.get("/devices")
async def devices_page(
    request: Request,
    user: User = Depends(require_login),
    settings: Settings = Depends(get_settings),
    q: str = "",
    status: str = "",
    reservation: str = "",
    lease: str = "",
    subnet_key: str = "",
    vendor: str = "",
    sort: str = "",
):
    config, devices, _leases, _history, log_unavailable = _load_devices(settings)
    rows = _apply_filters(devices, q, status, reservation, lease, subnet_key, vendor, sort)
    return render(
        request,
        "devices/list.html",
        user=user,
        rows=rows,
        total_count=len(devices),
        q=q,
        status=status,
        reservation=reservation,
        lease=lease,
        subnet_key=subnet_key,
        vendor=vendor,
        sort=sort,
        status_options=STATUS_OPTIONS,
        subnets=config.subnets,
        log_unavailable=log_unavailable,
    )


@router.get("/devices/table")
async def devices_table(
    request: Request,
    user: User = Depends(require_login),
    settings: Settings = Depends(get_settings),
    q: str = "",
    status: str = "",
    reservation: str = "",
    lease: str = "",
    subnet_key: str = "",
    vendor: str = "",
    sort: str = "",
):
    _config, devices, _leases, _history, _log = _load_devices(settings)
    rows = _apply_filters(devices, q, status, reservation, lease, subnet_key, vendor, sort)
    return render(request, "devices/_table.html", user=user, rows=rows, sort=sort)


@router.get("/devices/export.csv")
async def export_devices_csv(
    user: User = Depends(require_login),
    settings: Settings = Depends(get_settings),
    q: str = "",
    status: str = "",
    reservation: str = "",
    lease: str = "",
    subnet_key: str = "",
    vendor: str = "",
    sort: str = "",
):
    _config, devices, _leases, _history, _log = _load_devices(settings)
    rows = _apply_filters(devices, q, status, reservation, lease, subnet_key, vendor, sort)
    csv_rows = [
        [
            device.mac,
            device.hostname or "",
            device.vendor or "",
            device.current_ip or "",
            f"{device.subnet.network}/{device.subnet.netmask}" if device.subnet else "",
            device.subnet.get("range") or "" if device.subnet else "",
            device.current_lease.binding_state if device.current_lease else "",
            device.reservation.name if device.reservation else "",
            device.first_seen.isoformat() if device.first_seen else "",
            device.last_seen.isoformat() if device.last_seen else "",
            device.status.value,
        ]
        for device in rows
    ]
    return csv_response(
        "devices.csv",
        ["mac", "hostname", "vendor", "current_ip", "subnet", "pool", "lease_state", "reservation", "first_seen", "last_seen", "status"],
        csv_rows,
    )


@router.get("/devices/{mac}/menu")
async def device_menu(
    mac: str,
    request: Request,
    user: User = Depends(require_login),
    settings: Settings = Depends(get_settings),
):
    config, devices, _leases, _history, _log = _load_devices(settings)
    device = find_device(devices, mac)
    deny_host = None
    if device and device.mac in denied_macs(config):
        deny_host = config.find_host(f"deny-{device.mac.replace(':', '')}")
    return render(request, "devices/_menu.html", user=user, device=device, deny_host=deny_host)


@router.get("/devices/{mac}")
async def device_detail(
    mac: str,
    request: Request,
    user: User = Depends(require_login),
    settings: Settings = Depends(get_settings),
):
    config, devices, current_leases, events, log_unavailable = _load_devices(settings)
    device = find_device(devices, mac)
    if device is None:
        set_flash(request, _("Device not found - no reservation, lease, or DHCP activity matches this MAC."), kind="error")
        return RedirectResponse("/devices", status_code=303)

    activity = [event for event in events if event.kind != "OTHER" and event.mac == device.mac] if not log_unavailable else []
    diagnosis = diagnose_client(
        config, current_leases, events, log_unavailable, mac=device.mac, ip=device.current_ip, logs_requests=get_backend(settings).logs_requests
    )

    return render(
        request,
        "devices/detail.html",
        user=user,
        device=device,
        activity=activity,
        log_unavailable=log_unavailable,
        diagnosis=diagnosis,
    )


@router.get("/devices/{mac}/lease")
async def device_lease_form(
    mac: str,
    request: Request,
    user: User = Depends(require_role("operator")),
    settings: Settings = Depends(get_settings),
    subnet_key: str = "",
):
    config, devices, current_leases, _history, _log = _load_devices(settings)
    device = find_device(devices, mac)
    if device is None:
        set_flash(request, _("Device not found."), kind="error")
        return RedirectResponse("/devices", status_code=303)

    if device.reservation is not None:
        # Never offer to create a second, conflicting reservation for a MAC
        # that already has one - send the admin to edit the existing one.
        set_flash(request, _("This device already has a reservation ('{name}') - edit it here.", name=device.reservation.name))
        return RedirectResponse(f"/reservations/{device.reservation.name}/edit", status_code=303)

    selected_subnet = config.find_subnet(subnet_key) if subnet_key else (device.subnet or (config.subnets[0] if config.subnets else None))
    suggestion = None
    subnet_map = None
    if selected_subnet is not None:
        subnet_map = build_subnet_map(config, selected_subnet, current_leases)
        suggestion = next_available_ip(subnet_map)

    return render(
        request,
        "devices/lease.html",
        user=user,
        device=device,
        subnets=config.subnets,
        selected_subnet=selected_subnet,
        subnet_map=subnet_map,
        suggestion=suggestion,
    )


def _deleted_message(settings: Settings, removed: int, ip: str) -> str:
    if get_backend(settings).name == "kea":
        return _("Kea deleted the lease for {ip}. If the device is still using the address, it gets a new lease when it next renews.", ip=ip)
    return _("Deleted {removed} lease record(s) for {ip}. This is Sandia's copy only - if the device is still active, dhcpd will write a new record on its next renewal.", removed=removed, ip=ip)


@router.post("/devices/{mac}/delete-lease")
async def delete_device_lease(
    mac: str,
    request: Request,
    user: User = Depends(require_role("operator")),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    _config, devices, _leases, _history, _log = _load_devices(settings)
    device = find_device(devices, mac)
    if device is None or device.current_lease is None:
        set_flash(request, _("This device has no current lease record to delete."), kind="error")
        return RedirectResponse(f"/devices/{mac}", status_code=303)

    ip = device.current_lease.ip
    removed, error = await get_backend(settings).delete_leases(settings, [ip])
    if error:
        log_action(session, request, user, "device_lease_delete_failed", error, success=False)
        set_flash(request, _("Failed to delete lease record: {exc}", exc=error), kind="error")
        return RedirectResponse(f"/devices/{mac}", status_code=303)
    if removed == 0:
        set_flash(request, _("No lease record found for that address."), kind="error")
        return RedirectResponse(f"/devices/{mac}", status_code=303)

    log_action(session, request, user, "device_lease_delete", f"{device.mac} ({ip}), {removed} record(s)")
    set_flash(request, _deleted_message(settings, removed, ip))
    return RedirectResponse(f"/devices/{mac}", status_code=303)


@router.post("/devices/bulk-delete-lease")
async def bulk_delete_device_leases(
    request: Request,
    user: User = Depends(require_role("operator")),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    macs: list[str] = Form(default=[]),
):
    if not macs:
        set_flash(request, _("No devices selected."), kind="error")
        return RedirectResponse("/devices", status_code=303)

    _config, devices, _leases, _history, _log = _load_devices(settings)
    targets = {}
    for raw_mac in macs:
        device = find_device(devices, raw_mac)
        if device is not None and device.current_lease is not None:
            targets[device.mac] = device.current_lease.ip

    removed_total, error = await get_backend(settings).delete_leases(settings, list(targets.values()))
    if error:
        log_action(session, request, user, "device_bulk_lease_delete_failed", error, success=False)
        set_flash(request, _("Failed to delete lease record: {exc}", exc=error), kind="error")
        return RedirectResponse("/devices", status_code=303)
    if removed_total == 0:
        set_flash(request, _("None of the selected devices had a current lease record to delete."), kind="error")
        return RedirectResponse("/devices", status_code=303)

    log_action(session, request, user, "device_bulk_lease_delete", f"{len(targets)} device(s): {', '.join(targets)}")
    set_flash(request, _("Deleted {removed_total} lease record(s) across {value} device(s).", removed_total=removed_total, value=len(targets)))
    return RedirectResponse("/devices", status_code=303)
