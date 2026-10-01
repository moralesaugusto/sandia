import ipaddress
from functools import lru_cache

from .dhcpd import DhcpdConfig, Parameter, Subnet
from .leases import Lease


def pool_ranges(subnet: Subnet) -> list[tuple[ipaddress.IPv4Address, ipaddress.IPv4Address]]:
    """Every `range` in the subnet (a Kea subnet can have several pools; so
    can a dhcpd subnet), in config order. Malformed ranges are skipped."""
    ranges = []
    for node in subnet.body:
        if not (isinstance(node, Parameter) and node.name == "range"):
            continue
        parts = node.value.split()
        if len(parts) != 2:
            continue
        try:
            ranges.append((ipaddress.IPv4Address(parts[0]), ipaddress.IPv4Address(parts[1])))
        except ValueError:
            continue
    return ranges


@lru_cache(maxsize=65536)
def _address(ip: str) -> ipaddress.IPv4Address | None:
    # Lease IPs are checked against many pools (map, utilization, change
    # impact); parsing each one once keeps that linear in practice.
    try:
        return ipaddress.IPv4Address(ip)
    except ValueError:
        return None


def in_pools(ranges: list[tuple[ipaddress.IPv4Address, ipaddress.IPv4Address]], ip: str) -> bool:
    address = _address(ip)
    return address is not None and any(start <= address <= end for start, end in ranges)


def pools_label(subnet: Subnet) -> str:
    return ", ".join(f"{start}-{end}" for start, end in pool_ranges(subnet))


def subnet_utilization(subnet: Subnet, leases: list[Lease]) -> tuple[int, int]:
    """Returns (active leases within the pool ranges, total addresses in them)."""
    ranges = pool_ranges(subnet)
    total = sum(int(end) - int(start) + 1 for start, end in ranges)
    used = sum(1 for lease in leases if lease.is_active and in_pools(ranges, lease.ip))
    return used, total


def find_containing_subnet(config: DhcpdConfig, ip: str) -> Subnet | None:
    """The subnet whose network/netmask actually contains this address -
    not necessarily the one with a matching pool range (an address can be
    a valid reservation on a subnet without falling inside its dynamic
    pool)."""
    address = _address(ip)
    if address is None:
        return None
    for subnet in config.subnets:
        network = _network(subnet.network, subnet.netmask)
        if network is not None and address in network:
            return subnet
    return None


@lru_cache(maxsize=4096)
def _network(network: str, netmask: str) -> ipaddress.IPv4Network | None:
    try:
        return ipaddress.IPv4Network(f"{network}/{netmask}", strict=False)
    except ValueError:
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
