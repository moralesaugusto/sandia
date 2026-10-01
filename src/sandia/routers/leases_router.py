import ipaddress
import shutil
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session

from ..audit import log_action
from ..config import Settings, get_settings
from ..config_store import load_live_config
from ..csv_export import csv_response
from ..db import get_session
from ..dhcpd import Host, Parameter
from ..dhcpd.apply import apply_config
from ..dhcpd.backend import get_backend, load_current_leases
from ..i18n import N_, _
from ..leases import Lease, parse_lease_timestamp
from ..leases_cleanup import clean_leases_text
from ..models import User
from ..rendering import render, set_flash
from ..security import require_login, require_role
from ..vendors import lookup_vendor

router = APIRouter()

# "" means "All states" - no filtering. Anything else is matched against
# Lease.binding_state (see leases.py). Default query param value is
# "active": the leases file accumulates stale/expired history dhcpd never
# removes, so an unfiltered view is mostly noise for day-to-day use.
STATE_OPTIONS = [
    ("", N_("All states")),
    ("active", N_("Active")),
    ("free", N_("Free")),
    ("expired", N_("Expired")),
    ("released", N_("Released")),
    ("abandoned", N_("Abandoned")),
    ("backup", N_("Backup")),
    ("reset", N_("Reset")),
]


def _filter_leases(leases: list[Lease], q: str) -> list[Lease]:
    if not q:
        return leases
    needle = q.lower()
    return [
        lease
        for lease in leases
        if needle in lease.ip.lower()
        or needle in (lease.mac or "").lower()
        or needle in (lease.hostname or "").lower()
    ]


def _filter_by_state(leases: list[Lease], state: str) -> list[Lease]:
    if not state:
        return leases
    return [lease for lease in leases if (lease.binding_state or "").lower() == state.lower()]


def _ip_sort_key(ip: str) -> tuple[int, int]:
    try:
        return (0, int(ipaddress.IPv4Address(ip)))
    except ValueError:
        return (1, 0)


# Column key -> sort value, for the clickable table headers (see
# leases/_table.html). "sort" is the column key, optionally prefixed with
# "-" for descending (e.g. "ip", "-ends").
_SORT_KEYS = {
    "ip": lambda lease: _ip_sort_key(lease.ip),
    "mac": lambda lease: (lease.mac or "").lower(),
    "vendor": lambda lease: (lookup_vendor(lease.mac) or "").lower(),
    "hostname": lambda lease: (lease.hostname or "").lower(),
    "state": lambda lease: (lease.binding_state or "").lower(),
    "ends": lambda lease: parse_lease_timestamp(lease.ends) or datetime.min,
}


def _sort_leases(leases: list[Lease], sort: str) -> list[Lease]:
    if not sort:
        return leases
    descending = sort.startswith("-")
    key_fn = _SORT_KEYS.get(sort[1:] if descending else sort)
    if key_fn is None:
        return leases
    return sorted(leases, key=key_fn, reverse=descending)


@router.get("/leases")
async def leases_page(
    request: Request,
    user: User = Depends(require_login),
    settings: Settings = Depends(get_settings),
    q: str = "",
    state: str = "active",
    sort: str = "",
):
    leases = _sort_leases(_filter_by_state(_filter_leases(load_current_leases(settings), q), state), sort)
    reserved_macs = {host.mac for host in load_live_config(settings).all_hosts if host.mac}
    return render(
        request,
        "leases/list.html",
        user=user,
        leases=leases,
        q=q,
        state=state,
        sort=sort,
        state_options=STATE_OPTIONS,
        reserved_macs=reserved_macs,
    )


@router.get("/leases/table")
async def leases_table(
    request: Request,
    user: User = Depends(require_login),
    settings: Settings = Depends(get_settings),
    q: str = "",
    state: str = "active",
    sort: str = "",
):
    leases = _sort_leases(_filter_by_state(_filter_leases(load_current_leases(settings), q), state), sort)
    reserved_macs = {host.mac for host in load_live_config(settings).all_hosts if host.mac}
    return render(request, "leases/_table.html", user=user, leases=leases, reserved_macs=reserved_macs, sort=sort)


@router.get("/leases/export.csv")
async def export_leases_csv(
    user: User = Depends(require_login),
    settings: Settings = Depends(get_settings),
    q: str = "",
    state: str = "active",
    sort: str = "",
):
    leases = _sort_leases(_filter_by_state(_filter_leases(load_current_leases(settings), q), state), sort)
    rows = [
        [lease.ip, lease.mac or "", lookup_vendor(lease.mac) or "", lease.hostname or "", lease.binding_state or "", lease.starts or "", lease.ends or ""]
        for lease in leases
    ]
    return csv_response(
        "leases.csv",
        ["ip", "mac", "vendor", "hostname", "binding_state", "starts", "ends"],
        rows,
    )


@router.post("/leases/clean")
async def clean_leases(
    request: Request,
    user: User = Depends(require_role("operator")),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    """Compact the leases file: keep only the current (last) block per IP,
    dropping superseded renewal history. Never touches any other content
    in the file, and backs up the original first. dhcpd only - Kea's lease
    file cleanup (LFC) compacts kea-leases4.csv itself."""
    if not get_backend(settings).lease_file_cleanup:
        set_flash(request, _("Kea compacts its lease file itself (lfc-interval in kea-dhcp4.conf) - there is nothing for Sandia to clean."))
        return RedirectResponse("/leases", status_code=303)
    if not settings.leases_path.exists():
        set_flash(request, _("No leases file found."), kind="error")
        return RedirectResponse("/leases", status_code=303)

    text = settings.leases_path.read_text()
    cleaned, removed = clean_leases_text(text)
    if removed == 0:
        set_flash(request, _("Leases file is already clean - no stale records found."))
        return RedirectResponse("/leases", status_code=303)

    try:
        settings.backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S%f")
        shutil.copyfile(settings.leases_path, settings.backup_dir / f"dhcpd.leases.{stamp}")
        settings.leases_path.write_text(cleaned)
    except OSError as exc:
        log_action(session, request, user, "leases_clean_failed", str(exc), success=False)
        set_flash(request, _("Failed to clean leases file: {exc}", exc=exc), kind="error")
        return RedirectResponse("/leases", status_code=303)

    log_action(session, request, user, "leases_clean", f"removed {removed} stale lease record(s)")
    set_flash(request, _("Cleaned {removed} stale lease record(s) from the leases file.", removed=removed))
    return RedirectResponse("/leases", status_code=303)


@router.get("/leases/{ip}/menu")
async def lease_menu(
    ip: str,
    request: Request,
    user: User = Depends(require_login),
    settings: Settings = Depends(get_settings),
):
    leases = load_current_leases(settings)
    lease = next((lease for lease in leases if lease.ip == ip), None)
    config = load_live_config(settings)
    reserved_host = None
    if lease and lease.mac:
        reserved_host = next((h for h in config.all_hosts if h.mac == lease.mac), None)
    return render(request, "leases/_menu.html", user=user, lease=lease, reserved_host=reserved_host)


@router.post("/leases/{ip}/deny")
async def deny_lease(
    ip: str,
    request: Request,
    user: User = Depends(require_role("operator")),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    leases = load_current_leases(settings)
    lease = next((lease for lease in leases if lease.ip == ip), None)
    if lease is None or not lease.mac:
        set_flash(request, _("Lease not found or has no MAC address."), kind="error")
        return RedirectResponse("/leases", status_code=303)

    config = load_live_config(settings)
    name = f"deny-{lease.mac.replace(':', '')}"
    if config.find_host(name) is not None:
        set_flash(request, _("This client is already denied."), kind="error")
        return RedirectResponse("/leases", status_code=303)

    host = Host(name=name, body=[])
    host.set_mac(lease.mac)
    host.body.append(Parameter("deny", "booting"))
    config.nodes.append(host)

    result = await apply_config(settings, config)
    if not result.ok:
        log_action(session, request, user, "lease_deny_failed", result.output, success=False)
        set_flash(request, _("Apply failed ({stage}): {output}", stage=result.stage, output=result.output), kind="error")
        return RedirectResponse("/leases", status_code=303)

    log_action(session, request, user, "lease_deny", f"{lease.mac} ({ip})")
    set_flash(request, _("Client denied. Configuration applied."))
    return RedirectResponse("/leases", status_code=303)
