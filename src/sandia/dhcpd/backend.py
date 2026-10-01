
"""The operations that differ between the DHCP servers Sandia can manage
(SANDIA_DHCP_BACKEND: "kea", the default and supported backend, or the
legacy "isc"). Everything else - service control via systemctl, the
apply/rollback pipeline, the UI - is shared and calls through here.

Both backends are edited through the same config model (dhcpd/ast.py): ISC
serializes it to dhcpd.conf, Kea maps it back onto kea-dhcp4.conf (see
dhcpd/kea.py).
"""

from __future__ import annotations

import hashlib
import shutil
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .. import leases
from ..config import Settings
from ..interfaces_conf import read_configured_interfaces
from ..leases_cleanup import delete_lease_records
from . import kea
from .ast import DhcpdConfig
from .kea_ctrl import KeaControlError, send_command
from .parser import ParseError, parse
from .serializer import serialize


def _parse_isc_log(text: str) -> list:
    # diagnostics/__init__ imports dhcpd.apply, which imports this module.
    from ..diagnostics.dhcp_log import parse_dhcp_log

    return parse_dhcp_log(text)


def _parse_kea_log(text: str) -> list:
    from ..diagnostics.kea_log import parse_kea_log

    return parse_kea_log(text)


async def _delete_isc_leases(settings: Settings, ips: list[str]) -> tuple[int, str | None]:
    """Remove every dhcpd.leases block for these IPs (Sandia's copy only -
    there is no live channel to dhcpd), after backing the file up."""
    if not settings.leases_path.exists():
        return 0, "No leases file found."
    text = settings.leases_path.read_text()
    removed_total = 0
    for ip in ips:
        text, removed = delete_lease_records(text, ip)
        removed_total += removed
    if removed_total:
        try:
            settings.backup_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S%f")
            shutil.copyfile(settings.leases_path, settings.backup_dir / f"dhcpd.leases.{stamp}")
            settings.leases_path.write_text(text)
        except OSError as exc:
            return 0, str(exc)
    return removed_total, None


async def _delete_kea_leases(settings: Settings, ips: list[str]) -> tuple[int, str | None]:
    """lease4-del through the control socket: Kea removes the lease from its
    own database (and records the deletion in its lease file)."""
    if settings.dummy_data:
        # Simulated the way memfile persists a deletion: a row with
        # valid_lifetime 0. Dummy mode has no running Kea to ask.
        known = {lease.ip for lease in load_current_leases(settings)}
        rows = [f"{ip},,,0,{int(datetime.now().timestamp())},0,0,0,,0,,0\n" for ip in ips if ip in known]
        with settings.leases_path.open("a") as handle:
            handle.writelines(rows)
        return len(rows), None
    deleted = 0
    for ip in ips:
        try:
            response = await send_command(settings.kea_control_socket, "lease4-del", {"ip-address": ip})
        except KeaControlError as exc:
            return deleted, str(exc)
        result = response.get("result")
        if result == 0:
            deleted += 1
        elif result != 3:  # 3 = no such lease
            return deleted, f"lease4-del {ip}: {response.get('text') or f'result {result}'}"
    return deleted, None


def _kea_interfaces(settings: Settings) -> list[str]:
    try:
        return kea.configured_interfaces(live_config_text(settings) or "{}")
    except ParseError:
        return []


@dataclass(frozen=True)
class Backend:
    name: str
    label: str  # how the server is named in UI text
    validator: str  # the binary that validates a config file
    check_args: Callable[[Path], tuple[str, ...]]
    backup_prefix: str
    parse_config: Callable[[str], DhcpdConfig]
    # (current config file text, edited model) -> new config file text
    render_config: Callable[[str, DhcpdConfig], str]
    # ISC shows the round-tripped config; Kea shows the file verbatim.
    raw_text: Callable[[str], str]
    read_leases_text: Callable[[Path], str]
    parse_leases: Callable[[str], list[leases.Lease]]
    parse_lease_history: Callable[[str], list[leases.Lease]]
    parse_log: Callable[[str], list]
    # (settings, IPs) -> (leases deleted, error or None)
    delete_leases: Callable[[Settings, list[str]], Awaitable[tuple[int, str | None]]]
    listening_interfaces: Callable[[Settings], list[str]]
    # dhcpd never compacts on demand, so Sandia offers it; Kea's LFC does it.
    lease_file_cleanup: bool
    # Whether DISCOVER/REQUEST/NAK appear in the log at default severity
    # (dhcpd: yes; Kea: only at debug).
    logs_requests: bool


KEA = Backend(
    name="kea",
    label="Kea DHCPv4",
    validator="kea-dhcp4",
    check_args=lambda path: ("kea-dhcp4", "-t", str(path)),
    backup_prefix="kea-dhcp4.conf",
    parse_config=kea.parse_kea_config,
    render_config=kea.render_kea_config,
    raw_text=lambda text: text,
    read_leases_text=kea.read_kea_leases_text,
    parse_leases=kea.parse_kea_leases,
    parse_lease_history=kea.parse_kea_lease_history,
    parse_log=_parse_kea_log,
    delete_leases=_delete_kea_leases,
    listening_interfaces=_kea_interfaces,
    lease_file_cleanup=False,
    logs_requests=False,
)

ISC = Backend(
    name="isc",
    label="isc-dhcp-server",
    validator="dhcpd",
    check_args=lambda path: ("dhcpd", "-t", "-cf", str(path)),
    backup_prefix="dhcpd.conf",
    parse_config=parse,
    render_config=lambda _text, config: serialize(config),
    raw_text=lambda text: serialize(parse(text)),
    read_leases_text=lambda path: path.read_text(),
    parse_leases=leases.parse_leases,
    parse_lease_history=leases.parse_lease_history,
    parse_log=_parse_isc_log,
    delete_leases=_delete_isc_leases,
    listening_interfaces=lambda settings: read_configured_interfaces(settings.interfaces_conf_path),
    lease_file_cleanup=True,
    logs_requests=True,
)

_BACKENDS = {backend.name: backend for backend in (KEA, ISC)}


def get_backend(settings: Settings) -> Backend:
    return _BACKENDS[settings.dhcp_backend]


def live_config_text(settings: Settings) -> str | None:
    """The live config file, falling back to the last staged draft when no
    live file exists yet (e.g. the server not installed on this box during
    development)."""
    for path in (settings.dhcpd_conf_path, settings.staging_path):
        if path.exists():
            return path.read_text()
    return None


def live_config_sha(settings: Settings) -> str:
    """Hash of the config file on disk ("" when there is none), to notice
    that it changed between preparing a change and applying it."""
    path = settings.dhcpd_conf_path
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ""


def load_current_leases(settings: Settings) -> list[leases.Lease]:
    if not settings.leases_path.exists():
        return []
    backend = get_backend(settings)
    return backend.parse_leases(backend.read_leases_text(settings.leases_path))


def load_lease_records(settings: Settings) -> list[leases.Lease]:
    """Every historical lease record (see leases.parse_lease_history)."""
    if not settings.leases_path.exists():
        return []
    backend = get_backend(settings)
    return backend.parse_lease_history(backend.read_leases_text(settings.leases_path))
