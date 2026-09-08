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

from ..dhcpd import DhcpdConfig, Subnet
from ..dhcpd.subnet_interface import get_subnet_interface
from ..leases import Lease
from ..utilization import range_bounds, subnet_utilization
from .models import Action, Confidence, DiagnosticResult, Evidence, Finding, Status

HIGH_UTILIZATION_THRESHOLD = 0.9


def _subnet_label(subnet: Subnet) -> str:
    return f"{subnet.network}/{subnet.netmask}"


def _map_action(subnet: Subnet) -> Action:
    return Action("View subnet map", f"/subnets/{subnet.key}/map")


def _leases_action(state: str = "") -> Action:
    suffix = f"?state={state}" if state else ""
    return Action("View leases", f"/leases{suffix}")


def _reservations_action() -> Action:
    return Action("View reservations", "/reservations")


def pool_finding(subnet: Subnet, leases: list[Lease]) -> Finding | None:
    bounds = range_bounds(subnet)
    if bounds is None:
        return Finding(
            status=Status.WARNING,
            problem="No pool range configured",
            root_cause=f"Subnet {_subnet_label(subnet)} has no `range` statement, so it cannot hand out dynamic leases.",
            confidence=Confidence.CONFIRMED,
            evidence=[Evidence("Subnet", _subnet_label(subnet)), Evidence("range", "not set")],
            impact="Clients without a reservation on this subnet cannot obtain an address.",
            actions=[Action("Edit subnet", f"/subnets/{subnet.key}/edit")],
        )

    used, total = subnet_utilization(subnet, leases)
    if total == 0:
        return None
    ratio = used / total

    if used >= total:
        return Finding(
            status=Status.CRITICAL,
            problem="DHCP pool exhausted",
            root_cause="All usable addresses in the pool are currently allocated to active leases.",
            confidence=Confidence.CONFIRMED,
            evidence=[
                Evidence("Pool", subnet.get("range") or ""),
                Evidence("Usable", str(total)),
                Evidence("Allocated", str(used)),
                Evidence("Available", str(total - used)),
            ],
            impact="New clients cannot obtain leases on this subnet until an existing lease expires or is freed.",
            actions=[_leases_action("active"), _map_action(subnet)],
        )

    if ratio >= HIGH_UTILIZATION_THRESHOLD:
        return Finding(
            status=Status.WARNING,
            problem="High pool utilization",
            root_cause=f"{used} of {total} addresses ({ratio * 100:.0f}%) are currently allocated.",
            confidence=Confidence.CONFIRMED,
            evidence=[
                Evidence("Pool", subnet.get("range") or ""),
                Evidence("Usable", str(total)),
                Evidence("Allocated", str(used)),
                Evidence("Available", str(total - used)),
            ],
            impact="This subnet is close to exhaustion; new clients may soon be unable to obtain a lease.",
            actions=[_leases_action("active"), _map_action(subnet)],
        )

    return None


def abandoned_leases_finding(subnet: Subnet, leases: list[Lease]) -> Finding | None:
    bounds = range_bounds(subnet)
    if bounds is None:
        return None
    start, end = bounds
    abandoned = []
    for lease in leases:
        if (lease.binding_state or "").lower() != "abandoned":
            continue
        try:
            ip = ipaddress.IPv4Address(lease.ip)
        except ValueError:
            continue
        if start <= ip <= end:
            abandoned.append(lease)

    if not abandoned:
        return None

    return Finding(
        status=Status.WARNING,
        problem=f"{len(abandoned)} abandoned address(es) in this pool",
        root_cause=(
            "dhcpd marked these addresses abandoned, meaning a client declined them (DHCPDECLINE) or dhcpd "
            "could not verify them as free - typically because another device is already using that IP outside DHCP."
        ),
        confidence=Confidence.STRONG,
        evidence=[Evidence("Abandoned addresses", ", ".join(lease.ip for lease in abandoned))],
        impact="Abandoned addresses are excluded from the available pool until manually cleared, reducing effective pool size.",
        actions=[_leases_action("abandoned"), _map_action(subnet)],
    )


def range_validity_finding(subnet: Subnet) -> Finding | None:
    range_value = subnet.get("range")
    if not range_value:
        return None
    parts = range_value.split()
    if len(parts) != 2:
        return Finding(
            status=Status.CRITICAL,
            problem="Malformed pool range",
            root_cause=f"The `range` statement (`{range_value}`) does not have exactly two addresses.",
            confidence=Confidence.CONFIRMED,
            evidence=[Evidence("range", range_value)],
            impact="This subnet will fail config validation and cannot be applied.",
            actions=[Action("Edit subnet", f"/subnets/{subnet.key}/edit")],
        )
    try:
        start = ipaddress.IPv4Address(parts[0])
        end = ipaddress.IPv4Address(parts[1])
    except ValueError:
        return Finding(
            status=Status.CRITICAL,
            problem="Malformed pool range",
            root_cause=f"`{range_value}` does not contain two valid IPv4 addresses.",
            confidence=Confidence.CONFIRMED,
            evidence=[Evidence("range", range_value)],
            impact="This subnet will fail config validation and cannot be applied.",
            actions=[Action("Edit subnet", f"/subnets/{subnet.key}/edit")],
        )

    if start > end:
        return Finding(
            status=Status.CRITICAL,
            problem="Pool range is backwards",
            root_cause=f"The range start ({start}) is after the range end ({end}).",
            confidence=Confidence.CONFIRMED,
            evidence=[Evidence("range", range_value)],
            impact="dhcpd will reject this configuration.",
            actions=[Action("Edit subnet", f"/subnets/{subnet.key}/edit")],
        )

    try:
        network = ipaddress.ip_network(f"{subnet.network}/{subnet.netmask}", strict=False)
    except ValueError:
        return None
    if start not in network or end not in network:
        return Finding(
            status=Status.CRITICAL,
            problem="Pool range outside subnet network",
            root_cause=f"The pool range {start}-{end} is not contained within {network}.",
            confidence=Confidence.CONFIRMED,
            evidence=[Evidence("Subnet network", str(network)), Evidence("range", range_value)],
            impact="dhcpd will reject this configuration.",
            actions=[Action("Edit subnet", f"/subnets/{subnet.key}/edit")],
        )
    return None


def overlap_findings(config: DhcpdConfig, subnet: Subnet) -> list[Finding]:
    bounds = range_bounds(subnet)
    if bounds is None:
        return []
    start, end = bounds

    findings = []
    for other in config.subnets:
        if other is subnet or other.key == subnet.key:
            continue
        other_bounds = range_bounds(other)
        if other_bounds is None:
            continue
        other_start, other_end = other_bounds
        if start <= other_end and other_start <= end:
            findings.append(
                Finding(
                    status=Status.CRITICAL,
                    problem="Pool range overlaps another subnet",
                    root_cause=f"This subnet's pool ({start}-{end}) overlaps {_subnet_label(other)}'s pool ({other_start}-{other_end}).",
                    confidence=Confidence.CONFIRMED,
                    evidence=[
                        Evidence("This pool", f"{start}-{end}"),
                        Evidence("Overlapping subnet", _subnet_label(other)),
                        Evidence("Overlapping pool", f"{other_start}-{other_end}"),
                    ],
                    impact="dhcpd's behavior when two pools can hand out the same address is undefined; a client could be offered an address another subnet is already using.",
                    actions=[_map_action(subnet), _map_action(other)],
                )
            )
    return findings


def duplicate_reservation_findings(config: DhcpdConfig, subnet: Subnet) -> list[Finding]:
    all_hosts = config.all_hosts
    findings = []
    for host in subnet.hosts:
        if host.fixed_address:
            duplicates = [h for h in all_hosts if h.fixed_address == host.fixed_address and h.name != host.name]
            if duplicates:
                names = sorted({host.name, *(d.name for d in duplicates)})
                findings.append(
                    Finding(
                        status=Status.CRITICAL,
                        problem="Duplicate reservation IP address",
                        root_cause=f"{len(names)} reservations declare the same fixed address ({host.fixed_address}).",
                        confidence=Confidence.CONFIRMED,
                        evidence=[Evidence("Fixed address", host.fixed_address), Evidence("Reservations", ", ".join(names))],
                        impact="dhcpd's behavior is undefined when two reservations claim the same address; the wrong client may receive it, or neither will.",
                        actions=[Action(f"Edit {name}", f"/reservations/{name}/edit") for name in names] + [_reservations_action()],
                    )
                )
        if host.mac:
            duplicates = [h for h in all_hosts if h.mac == host.mac and h.name != host.name]
            if duplicates:
                names = sorted({host.name, *(d.name for d in duplicates)})
                findings.append(
                    Finding(
                        status=Status.CRITICAL,
                        problem="Duplicate reservation MAC address",
                        root_cause=f"{len(names)} reservations declare the same hardware address ({host.mac}).",
                        confidence=Confidence.CONFIRMED,
                        evidence=[Evidence("MAC address", host.mac), Evidence("Reservations", ", ".join(names))],
                        impact="dhcpd will only honor one of these reservations for this client; which one is unpredictable.",
                        actions=[Action(f"Edit {name}", f"/reservations/{name}/edit") for name in names] + [_reservations_action()],
                    )
                )

    # de-duplicate: the loop above can produce the same finding twice (once per host in the pair)
    seen: set[tuple[str, str]] = set()
    unique: list[Finding] = []
    for finding in findings:
        key = (finding.problem, finding.evidence[0].value if finding.evidence else "")
        if key in seen:
            continue
        seen.add(key)
        unique.append(finding)
    return unique


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
                    problem="Reservation has no MAC address",
                    root_cause=f"Reservation '{host.name}' has no `hardware ethernet` statement.",
                    confidence=Confidence.CONFIRMED,
                    evidence=[Evidence("Reservation", host.name)],
                    impact="dhcpd cannot match any client to this reservation.",
                    actions=[Action("Edit reservation", f"/reservations/{host.name}/edit")],
                )
            )
        if not host.fixed_address:
            findings.append(
                Finding(
                    status=Status.WARNING,
                    problem="Reservation has no fixed address",
                    root_cause=f"Reservation '{host.name}' has no `fixed-address` statement.",
                    confidence=Confidence.CONFIRMED,
                    evidence=[Evidence("Reservation", host.name)],
                    impact="This reservation has no effect - the client will be treated as a dynamic (non-reserved) client.",
                    actions=[Action("Edit reservation", f"/reservations/{host.name}/edit")],
                )
            )
            continue
        try:
            ip = ipaddress.IPv4Address(host.fixed_address)
        except ValueError:
            findings.append(
                Finding(
                    status=Status.CRITICAL,
                    problem="Reservation has an invalid fixed address",
                    root_cause=f"'{host.fixed_address}' on reservation '{host.name}' is not a valid IPv4 address.",
                    confidence=Confidence.CONFIRMED,
                    evidence=[Evidence("Reservation", host.name), Evidence("fixed-address", host.fixed_address)],
                    impact="This subnet will fail config validation and cannot be applied.",
                    actions=[Action("Edit reservation", f"/reservations/{host.name}/edit")],
                )
            )
            continue
        if ip not in network:
            findings.append(
                Finding(
                    status=Status.WARNING,
                    problem="Reservation address outside subnet network",
                    root_cause=f"Reservation '{host.name}' is fixed to {ip}, which is not part of {network}.",
                    confidence=Confidence.CONFIRMED,
                    evidence=[Evidence("Reservation", host.name), Evidence("fixed-address", str(ip)), Evidence("Subnet network", str(network))],
                    impact="This reservation is nested under a subnet it doesn't belong to, which is confusing and may indicate a typo.",
                    actions=[Action("Edit reservation", f"/reservations/{host.name}/edit")],
                )
            )
    return findings


def interface_mismatch_finding(config: DhcpdConfig, subnet: Subnet, configured_interfaces: list[str]) -> Finding | None:
    tag = get_subnet_interface(config, subnet)
    if not tag or tag in configured_interfaces:
        return None
    return Finding(
        status=Status.WARNING,
        problem="Subnet tagged with an interface dhcpd isn't listening on",
        root_cause=f"This subnet is tagged `{tag}`, but INTERFACESv4 does not include it.",
        confidence=Confidence.CONFIRMED,
        evidence=[Evidence("Interface tag", tag), Evidence("Listening interfaces", ", ".join(configured_interfaces) or "(none)")],
        impact="If this subnet's traffic actually arrives on that interface, dhcpd never sees it and cannot hand out leases for this subnet.",
        actions=[Action("Edit interfaces", "/interfaces")],
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
                problem="No issues detected",
                root_cause="",
                confidence=Confidence.CONFIRMED,
                evidence=[
                    Evidence("Pool utilization", f"{used}/{total} used" if total else "no pool configured"),
                    Evidence("Reservations", str(len(subnet.hosts))),
                ],
            )
        )

    return DiagnosticResult(title=f"Subnet {_subnet_label(subnet)}", target_description=_subnet_label(subnet), findings=findings)
