import ipaddress

from .dhcpd import DhcpdConfig, Subnet
from .leases import Lease


def range_bounds(subnet: Subnet) -> tuple[ipaddress.IPv4Address, ipaddress.IPv4Address] | None:
    range_value = subnet.get("range")
    if not range_value:
        return None
    parts = range_value.split()
    if len(parts) != 2:
        return None
    try:
        return ipaddress.IPv4Address(parts[0]), ipaddress.IPv4Address(parts[1])
    except ValueError:
        return None


def subnet_utilization(subnet: Subnet, leases: list[Lease]) -> tuple[int, int]:
    """Returns (active leases within the pool range, total addresses in the range)."""
    bounds = range_bounds(subnet)
    if bounds is None:
        return 0, 0
    start, end = bounds
    total = int(end) - int(start) + 1
    used = 0
    for lease in leases:
        if not lease.is_active:
            continue
        try:
            ip = ipaddress.IPv4Address(lease.ip)
        except ValueError:
            continue
        if start <= ip <= end:
            used += 1
    return used, total


def find_containing_subnet(config: DhcpdConfig, ip: str) -> Subnet | None:
    """The subnet whose network/netmask actually contains this address -
    not necessarily the one with a matching pool range (an address can be
    a valid reservation on a subnet without falling inside its dynamic
    pool)."""
    try:
        address = ipaddress.IPv4Address(ip)
    except ValueError:
        return None
    for subnet in config.subnets:
        try:
            network = ipaddress.ip_network(f"{subnet.network}/{subnet.netmask}", strict=False)
        except ValueError:
            continue
        if address in network:
            return subnet
    return None


def utilization_color(used: int, total: int) -> str:
    """Tailwind bg-* class for a utilization bar, color-coded like most IPAM
    tools: green under 70%, amber 70-90%, red above 90%."""
    if not total:
        return "bg-slate-700"
    pct = used / total * 100
    if pct >= 90:
        return "bg-red-500"
    if pct >= 70:
        return "bg-amber-500"
    return "bg-emerald-600"
