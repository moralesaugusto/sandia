"""Per-IP subnet visualization: builds the data for the SVG grid on the
subnet map page (one cell per address in the subnet's pool range)."""

from __future__ import annotations

import ipaddress
import math
from dataclasses import dataclass

from .dhcpd import DhcpdConfig, Host, Subnet
from .leases import Lease
from .utilization import range_bounds

# A /22 (1024 addresses). Above this, rendering one SVG rect per address
# server-side stops being worth it - see docs/DECISIONS.md.
MAX_CELLS = 1024

# Cap grid width so small subnets don't render as one absurdly wide row and
# large ones stay roughly square on screen.
MAX_COLUMNS = 32


@dataclass
class Cell:
    ip: str
    index: int
    status: str  # "free" | "leased" | "reserved" | "reserved-online" | "denied"
    host: Host | None
    lease: Lease | None


@dataclass
class SubnetMap:
    subnet: Subnet
    total: int
    cells: list[Cell]
    too_large: bool
    outside_range: list[Host]

    @property
    def columns(self) -> int:
        if self.total <= 0:
            return 1
        return min(MAX_COLUMNS, max(1, math.ceil(math.sqrt(self.total))))

    @property
    def rows(self) -> int:
        if self.total <= 0:
            return 0
        return math.ceil(self.total / self.columns)


def _denied_macs(config: DhcpdConfig) -> set[str]:
    return {host.mac for host in config.all_hosts if host.mac and host.get("deny") == "booting"}


def build_subnet_map(config: DhcpdConfig, subnet: Subnet, leases: list[Lease]) -> SubnetMap:
    bounds = range_bounds(subnet)
    if bounds is None:
        return SubnetMap(subnet=subnet, total=0, cells=[], too_large=False, outside_range=list(subnet.hosts))

    start, end = bounds
    total = int(end) - int(start) + 1

    host_by_ip = {host.fixed_address: host for host in subnet.hosts if host.fixed_address}
    outside_range = [
        host
        for host in subnet.hosts
        if not host.fixed_address or not (start <= ipaddress.IPv4Address(host.fixed_address) <= end)
    ]

    if total > MAX_CELLS:
        return SubnetMap(subnet=subnet, total=total, cells=[], too_large=True, outside_range=outside_range)

    lease_by_ip = {lease.ip: lease for lease in leases}
    denied_macs = _denied_macs(config)

    cells: list[Cell] = []
    for index, ip_int in enumerate(range(int(start), int(end) + 1)):
        ip = str(ipaddress.IPv4Address(ip_int))
        host = host_by_ip.get(ip)
        lease = lease_by_ip.get(ip)
        active_lease = lease if lease and lease.is_active else None

        if host is not None:
            status = "reserved-online" if active_lease else "reserved"
        elif active_lease is not None:
            status = "denied" if active_lease.mac in denied_macs else "leased"
        else:
            status = "free"

        cells.append(Cell(ip=ip, index=index, status=status, host=host, lease=active_lease))

    return SubnetMap(subnet=subnet, total=total, cells=cells, too_large=False, outside_range=outside_range)


def find_cell(config: DhcpdConfig, subnet: Subnet, leases: list[Lease], ip: str) -> Cell | None:
    subnet_map = build_subnet_map(config, subnet, leases)
    return next((cell for cell in subnet_map.cells if cell.ip == ip), None)
