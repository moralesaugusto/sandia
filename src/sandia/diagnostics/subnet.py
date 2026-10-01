"""Deterministic subnet/pool health checks.

Every check here is a pure function over already-parsed config/leases data:
no I/O, no log correlation, no guessing. Each returns Finding|None (or a
list of Findings for checks that can fire more than once, e.g. duplicate
reservations). diagnose_subnet() below is the only thing that assembles
them into a DiagnosticResult; client.py reuses the pool-utilization check
directly rather than recomputing it, so "why is the pool full" is reported
identically whether you got there from the subnet map or a client lookup.
"""

from __future__ import annotations

import ipaddress
from collections import defaultdict

from ..dhcpd import DhcpdConfig, Host, Parameter, Subnet
from ..dhcpd.subnet_interface import get_subnet_interface
from ..i18n import _
from ..leases import Lease
from ..utilization import in_pools, pool_ranges, pools_label, subnet_utilization
from .models import Action, Confidence, DiagnosticResult, Evidence, Finding, Status

HIGH_UTILIZATION_THRESHOLD = 0.9


def _subnet_label(subnet: Subnet) -> str:
    return f"{subnet.network}/{subnet.netmask}"


def _map_action(subnet: Subnet) -> Action:
    return Action(_("View subnet map"), f"/subnets/{subnet.key}/map")


def _leases_action(state: str = "") -> Action:
    suffix = f"?state={state}" if state else ""
    return Action(_("View leases"), f"/leases{suffix}")


def _reservations_action() -> Action:
    return Action(_("View reservations"), "/reservations")


def pool_finding(subnet: Subnet, leases: list[Lease]) -> Finding | None:
    if not pool_ranges(subnet):
        return Finding(
            status=Status.WARNING,
            problem=_("No pool range configured"),
            root_cause=_("Subnet {value} has no `range` statement, so it cannot hand out dynamic leases.", value=_subnet_label(subnet)),
            confidence=Confidence.CONFIRMED,
            evidence=[Evidence(_("Subnet"), _subnet_label(subnet)), Evidence(_("range"), _("not set"))],
            impact=_("Clients without a reservation on this subnet cannot obtain an address."),
            actions=[Action(_("Edit subnet"), f"/subnets/{subnet.key}/edit")],
        )

    used, total = subnet_utilization(subnet, leases)
    if total == 0:
        return None
    ratio = used / total

    if used >= total:
        return Finding(
            status=Status.CRITICAL,
            problem=_("DHCP pool exhausted"),
            root_cause=_("All usable addresses in the pool are currently allocated to active leases."),
            confidence=Confidence.CONFIRMED,
            evidence=[
                Evidence(_("Pool"), pools_label(subnet)),
                Evidence(_("Usable"), str(total)),
                Evidence(_("Allocated"), str(used)),
                Evidence(_("Available"), str(total - used)),
            ],
            impact=_("New clients cannot obtain leases on this subnet until an existing lease expires or is freed."),
            actions=[_leases_action("active"), _map_action(subnet)],
            runtime=True,
        )

    if ratio >= HIGH_UTILIZATION_THRESHOLD:
        return Finding(
            status=Status.WARNING,
            problem=_("High pool utilization"),
            root_cause=_("{used} of {total} addresses ({value:.0f}%) are currently allocated.", used=used, total=total, value=ratio * 100),
            confidence=Confidence.CONFIRMED,
            evidence=[
                Evidence(_("Pool"), pools_label(subnet)),
                Evidence(_("Usable"), str(total)),
                Evidence(_("Allocated"), str(used)),
                Evidence(_("Available"), str(total - used)),
            ],
            impact=_("This subnet is close to exhaustion; new clients may soon be unable to obtain a lease."),
            actions=[_leases_action("active"), _map_action(subnet)],
            runtime=True,
        )

    return None


def abandoned_leases_finding(subnet: Subnet, leases: list[Lease]) -> Finding | None:
    ranges = pool_ranges(subnet)
    abandoned = [lease for lease in leases if (lease.binding_state or "").lower() == "abandoned" and in_pools(ranges, lease.ip)]

    if not abandoned:
        return None

    return Finding(
        status=Status.WARNING,
        problem=_("{value} abandoned address(es) in this pool", value=len(abandoned)),
        root_cause=(
            _("The DHCP server marked these addresses abandoned (declined), meaning a client declined them (DHCPDECLINE) or the server could not verify them as free - typically because another device is already using that IP outside DHCP.")
        ),
        confidence=Confidence.STRONG,
        evidence=[Evidence(_("Abandoned addresses"), ", ".join(lease.ip for lease in abandoned))],
        impact=_("Abandoned addresses are excluded from the available pool until manually cleared, reducing effective pool size."),
        actions=[_leases_action("abandoned"), _map_action(subnet)],
        runtime=True,
    )


def range_validity_finding(subnet: Subnet) -> Finding | None:
    """The first malformed `range` of the subnet (a subnet can have several)."""
    for node in subnet.body:
        if isinstance(node, Parameter) and node.name == "range":
            finding = _range_finding(subnet, node.value)
            if finding:
                return finding
    return None


def _range_finding(subnet: Subnet, range_value: str) -> Finding | None:
    parts = range_value.split()
    if len(parts) != 2:
        return Finding(
            status=Status.CRITICAL,
            problem=_("Malformed pool range"),
            root_cause=_("The `range` statement (`{range_value}`) does not have exactly two addresses.", range_value=range_value),
            confidence=Confidence.CONFIRMED,
            evidence=[Evidence(_("range"), range_value)],
            impact=_("This subnet will fail config validation and cannot be applied."),
            actions=[Action(_("Edit subnet"), f"/subnets/{subnet.key}/edit")],
        )
    try:
        start = ipaddress.IPv4Address(parts[0])
        end = ipaddress.IPv4Address(parts[1])
    except ValueError:
        return Finding(
            status=Status.CRITICAL,
            problem=_("Malformed pool range"),
            root_cause=_("`{range_value}` does not contain two valid IPv4 addresses.", range_value=range_value),
            confidence=Confidence.CONFIRMED,
            evidence=[Evidence(_("range"), range_value)],
            impact=_("This subnet will fail config validation and cannot be applied."),
            actions=[Action(_("Edit subnet"), f"/subnets/{subnet.key}/edit")],
        )

    if start > end:
        return Finding(
            status=Status.CRITICAL,
            problem=_("Pool range is backwards"),
            root_cause=_("The range start ({start}) is after the range end ({end}).", start=start, end=end),
            confidence=Confidence.CONFIRMED,
            evidence=[Evidence(_("range"), range_value)],
            impact=_("The DHCP server will reject this configuration."),
            actions=[Action(_("Edit subnet"), f"/subnets/{subnet.key}/edit")],
        )

    try:
        network = ipaddress.ip_network(f"{subnet.network}/{subnet.netmask}", strict=False)
    except ValueError:
        return None
    if start not in network or end not in network:
        return Finding(
            status=Status.CRITICAL,
            problem=_("Pool range outside subnet network"),
            root_cause=_("The pool range {start}-{end} is not contained within {network}.", start=start, end=end, network=network),
            confidence=Confidence.CONFIRMED,
            evidence=[Evidence(_("Subnet network"), str(network)), Evidence(_("range"), range_value)],
            impact=_("The DHCP server will reject this configuration."),
            actions=[Action(_("Edit subnet"), f"/subnets/{subnet.key}/edit")],
        )
    return None


def overlap_findings(config: DhcpdConfig, subnet: Subnet) -> list[Finding]:
    findings = []
    for other in config.subnets:
        if other is subnet or other.key == subnet.key:
            continue
        overlapping = [
            (start, end, other_start, other_end)
            for start, end in pool_ranges(subnet)
            for other_start, other_end in pool_ranges(other)
            if start <= other_end and other_start <= end
        ]
        for start, end, other_start, other_end in overlapping:
            findings.append(
                Finding(
                    status=Status.CRITICAL,
                    problem=_("Pool range overlaps another subnet"),
                    root_cause=_("This subnet's pool ({start}-{end}) overlaps {value}'s pool ({other_start}-{other_end}).", start=start, end=end, value=_subnet_label(other), other_start=other_start, other_end=other_end),
                    confidence=Confidence.CONFIRMED,
                    evidence=[
                        Evidence(_("This pool"), f"{start}-{end}"),
                        Evidence(_("Overlapping subnet"), _subnet_label(other)),
                        Evidence(_("Overlapping pool"), f"{other_start}-{other_end}"),
                    ],
                    impact=_("The DHCP server's behavior when two pools can hand out the same address is undefined; a client could be offered an address another subnet is already using."),
                    actions=[_map_action(subnet), _map_action(other)],
                )
            )
    return findings


def duplicate_reservation_findings(config: DhcpdConfig, subnet: Subnet) -> list[Finding]:
    return _duplicate_findings(subnet.hosts, config.all_hosts)


def _is_deny(host: Host) -> bool:
    return host.get("deny") == "booting"


def _duplicate_findings(hosts: list[Host], all_hosts: list[Host]) -> list[Finding]:
    # A deny entry shares its MAC with that client's reservation on purpose.
    names_by_ip: dict[str, set[str]] = defaultdict(set)
    names_by_mac: dict[str, set[str]] = defaultdict(set)
    for h in all_hosts:
        if _is_deny(h):
            continue
        if h.fixed_address:
            names_by_ip[h.fixed_address].add(h.name)
        if h.mac:
            names_by_mac[h.mac].add(h.name)

    findings = []
    reported: set[tuple[str, str]] = set()
    for host in hosts:
        if _is_deny(host):
            continue
        fixed_address, mac = host.fixed_address, host.mac
        if fixed_address and len(names_by_ip[fixed_address]) > 1 and ("ip", fixed_address) not in reported:
            reported.add(("ip", fixed_address))
            names = sorted(names_by_ip[fixed_address])
            findings.append(
                Finding(
                    status=Status.CRITICAL,
                    problem=_("Duplicate reservation IP address"),
                    root_cause=_("{value} reservations declare the same fixed address ({fixed_address}).", value=len(names), fixed_address=fixed_address),
                    confidence=Confidence.CONFIRMED,
                    evidence=[Evidence(_("Fixed address"), fixed_address), Evidence(_("Reservations"), ", ".join(names))],
                    impact=_("The DHCP server's behavior is undefined when two reservations claim the same address; the wrong client may receive it, or neither will."),
                    actions=[Action(_("Edit {name}", name=name), f"/reservations/{name}/edit") for name in names] + [_reservations_action()],
                )
            )
        if mac and len(names_by_mac[mac]) > 1 and ("mac", mac) not in reported:
            reported.add(("mac", mac))
            names = sorted(names_by_mac[mac])
            findings.append(
                Finding(
                    status=Status.CRITICAL,
                    problem=_("Duplicate reservation MAC address"),
                    root_cause=_("{value} reservations declare the same hardware address ({mac}).", value=len(names), mac=mac),
                    confidence=Confidence.CONFIRMED,
                    evidence=[Evidence(_("MAC address"), mac), Evidence(_("Reservations"), ", ".join(names))],
                    impact=_("The DHCP server will only honor one of these reservations for this client; which one is unpredictable."),
                    actions=[Action(_("Edit {name}", name=name), f"/reservations/{name}/edit") for name in names] + [_reservations_action()],
                )
            )
    return findings


def invalid_reservation_findings(subnet: Subnet) -> list[Finding]:
    try:
        network = ipaddress.ip_network(f"{subnet.network}/{subnet.netmask}", strict=False)
    except ValueError:
        return []

    findings = []
    for host in subnet.hosts:
        if not host.mac:
            findings.append(
                Finding(
                    status=Status.WARNING,
                    problem=_("Reservation has no MAC address"),
                    root_cause=_("Reservation '{name}' has no `hardware ethernet` statement.", name=host.name),
                    confidence=Confidence.CONFIRMED,
                    evidence=[Evidence(_("Reservation"), host.name)],
                    impact=_("The DHCP server cannot match any client to this reservation."),
                    actions=[Action(_("Edit reservation"), f"/reservations/{host.name}/edit")],
                )
            )
        if not host.fixed_address:
            findings.append(
                Finding(
                    status=Status.WARNING,
                    problem=_("Reservation has no fixed address"),
                    root_cause=_("Reservation '{name}' has no `fixed-address` statement.", name=host.name),
                    confidence=Confidence.CONFIRMED,
                    evidence=[Evidence(_("Reservation"), host.name)],
                    impact=_("This reservation has no effect - the client will be treated as a dynamic (non-reserved) client."),
                    actions=[Action(_("Edit reservation"), f"/reservations/{host.name}/edit")],
                )
            )
            continue
        try:
            ip = ipaddress.IPv4Address(host.fixed_address)
        except ValueError:
            findings.append(
                Finding(
                    status=Status.CRITICAL,
                    problem=_("Reservation has an invalid fixed address"),
                    root_cause=_("'{fixed_address}' on reservation '{name}' is not a valid IPv4 address.", fixed_address=host.fixed_address, name=host.name),
                    confidence=Confidence.CONFIRMED,
                    evidence=[Evidence(_("Reservation"), host.name), Evidence(_("fixed-address"), host.fixed_address)],
                    impact=_("This subnet will fail config validation and cannot be applied."),
                    actions=[Action(_("Edit reservation"), f"/reservations/{host.name}/edit")],
                )
            )
            continue
        if ip not in network:
            findings.append(
                Finding(
                    status=Status.WARNING,
                    problem=_("Reservation address outside subnet network"),
                    root_cause=_("Reservation '{name}' is fixed to {ip}, which is not part of {network}.", name=host.name, ip=ip, network=network),
                    confidence=Confidence.CONFIRMED,
                    evidence=[Evidence(_("Reservation"), host.name), Evidence(_("fixed-address"), str(ip)), Evidence(_("Subnet network"), str(network))],
                    impact=_("This reservation is nested under a subnet it doesn't belong to, which is confusing and may indicate a typo."),
                    actions=[Action(_("Edit reservation"), f"/reservations/{host.name}/edit")],
                )
            )
    return findings


def interface_mismatch_finding(config: DhcpdConfig, subnet: Subnet, configured_interfaces: list[str]) -> Finding | None:
    tag = get_subnet_interface(config, subnet)
    # Kea entries may be "*" (every interface) or "eth0/192.0.2.1".
    listening = {name.split("/")[0] for name in configured_interfaces}
    if not tag or tag in listening or "*" in listening:
        return None
    return Finding(
        status=Status.WARNING,
        problem=_("Subnet tagged with an interface the DHCP server isn't listening on"),
        root_cause=_("This subnet is tagged `{tag}`, but the server's listening interfaces don't include it.", tag=tag),
        confidence=Confidence.CONFIRMED,
        evidence=[Evidence(_("Interface tag"), tag), Evidence(_("Listening interfaces"), ", ".join(configured_interfaces) or "(none)")],
        impact=_("If this subnet's traffic actually arrives on that interface, the DHCP server never sees it and cannot hand out leases for this subnet."),
        actions=[Action(_("Edit interfaces"), "/interfaces")],
    )


def diagnose_subnet(config: DhcpdConfig, subnet: Subnet, leases: list[Lease], configured_interfaces: list[str]) -> DiagnosticResult:
    findings: list[Finding] = []

    range_finding = range_validity_finding(subnet)
    if range_finding:
        findings.append(range_finding)
    else:
        # Pool exhaustion/utilization only makes sense once we know the
        # range itself is well-formed.
        pf = pool_finding(subnet, leases)
        if pf:
            findings.append(pf)

    af = abandoned_leases_finding(subnet, leases)
    if af:
        findings.append(af)

    findings.extend(overlap_findings(config, subnet))
    findings.extend(duplicate_reservation_findings(config, subnet))
    findings.extend(invalid_reservation_findings(subnet))

    imf = interface_mismatch_finding(config, subnet, configured_interfaces)
    if imf:
        findings.append(imf)

    if not findings:
        used, total = subnet_utilization(subnet, leases)
        findings.append(
            Finding(
                status=Status.HEALTHY,
                problem=_("No issues detected"),
                root_cause="",
                confidence=Confidence.CONFIRMED,
                evidence=[
                    Evidence(_("Pool utilization"), _("{used}/{total} used", used=used, total=total) if total else _("no pool configured")),
                    Evidence(_("Reservations"), str(len(subnet.hosts))),
                ],
            )
        )

    return DiagnosticResult(title=_("Subnet {value}", value=_subnet_label(subnet)), target_description=_subnet_label(subnet), findings=findings)


def reserved_ip_conflict_findings(config: DhcpdConfig, leases: list[Lease]) -> list[Finding]:
    """A reserved address that an active lease gives to a different MAC.
    Observed from the lease file, so it is reported as something to
    investigate (a stale lease from before the reservation is the usual
    cause), not as a config fault."""
    active = {lease.ip: lease for lease in leases if lease.is_active and lease.mac}
    findings = []
    for host in config.all_hosts:
        lease = active.get(host.fixed_address or "")
        if not (lease and host.mac) or lease.mac.lower() == host.mac.lower():
            continue
        findings.append(
            Finding(
                status=Status.WARNING,
                problem=_("Reserved address leased to another device"),
                root_cause=_("{ip} is reserved for {mac} ('{name}'), but an active lease gives it to {lease_mac}.", ip=lease.ip, mac=host.mac, name=host.name, lease_mac=lease.mac),
                confidence=Confidence.STRONG,
                evidence=[
                    Evidence(_("Fixed address"), lease.ip),
                    Evidence(_("Reserved for"), host.mac),
                    Evidence(_("Leased to"), lease.mac),
                ],
                impact=_("The reserved device may not get its address until the other lease expires or is deleted."),
                actions=[
                    Action(_("Open device {mac}", mac=lease.mac), f"/devices/{lease.mac}"),
                    Action(_("Open device {mac}", mac=host.mac), f"/devices/{host.mac}"),
                    Action(_("Edit reservation"), f"/reservations/{host.name}/edit"),
                ],
                runtime=True,
            )
        )
    return findings


def finding_key(finding: Finding) -> tuple:
    """Identity of a finding across two scans (before/after a change). An
    overlap is the same whichever of the two subnets reported it."""
    values = [e.value for e in finding.evidence]
    if finding.problem == _("Pool range overlaps another subnet"):
        values = [values[0], values[2]]
    return finding.problem, frozenset(values)


def scan_config(config: DhcpdConfig, leases: list[Lease], configured_interfaces: list[str]) -> list[Finding]:
    """Every deterministic anomaly in a whole config, plus clearly marked
    runtime observations from the leases. No healthy placeholder."""
    findings: list[Finding] = []
    for subnet in config.subnets:
        range_finding = range_validity_finding(subnet)
        findings.append(range_finding or pool_finding(subnet, leases))
        findings.append(abandoned_leases_finding(subnet, leases))
        findings.extend(overlap_findings(config, subnet))
        findings.extend(invalid_reservation_findings(subnet))
        findings.append(interface_mismatch_finding(config, subnet, configured_interfaces))
    findings.extend(_duplicate_findings(config.all_hosts, config.all_hosts))
    findings.extend(reserved_ip_conflict_findings(config, leases))

    unique: dict[tuple, Finding] = {}
    for finding in findings:
        if finding is not None:
            unique.setdefault(finding_key(finding), finding)
    return sorted(unique.values(), key=lambda f: (f.runtime, -_rank(f.status)))


def _rank(status: Status) -> int:
    return {Status.CRITICAL: 3, Status.WARNING: 2, Status.UNKNOWN: 1, Status.HEALTHY: 0}[status]
