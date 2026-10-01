"""The flagship "why didn't this client get an IP" workflow.

Reconstructs the DHCP flow (Client -> DHCP activity -> Subnet -> Reservation
-> Pool -> Address availability -> DHCP response -> Lease) purely from
already-parsed config/leases/log data, and synthesizes a single root-cause
finding from whichever combination of evidence actually applies - see
_root_cause_findings() for the priority order. Never fabricates a step: any
stage with nothing to show renders as "unknown/insufficient evidence".
"""

from __future__ import annotations

from ..dhcpd import DhcpdConfig, Host, Subnet
from ..dhcpd.subnet_interface import get_subnet_interface
from ..i18n import _
from ..leases import Lease
from ..utilization import (
    find_containing_subnet,
    pool_ranges,
    pools_label,
    subnet_utilization,
)
from ..vendors import lookup_vendor
from . import dhcp_log
from .dhcp_log import DhcpEvent
from .models import (
    Action,
    Confidence,
    DiagnosticResult,
    Evidence,
    Finding,
    FlowStep,
    Status,
)
from .subnet import pool_finding


def _find_reservation_by_mac(config: DhcpdConfig, mac: str) -> Host | None:
    return next((host for host in config.all_hosts if host.mac == mac), None)


def _find_reservation_by_ip(config: DhcpdConfig, ip: str) -> Host | None:
    return next((host for host in config.all_hosts if host.fixed_address == ip), None)


def _most_recent(events: list[DhcpEvent], kind: str) -> DhcpEvent | None:
    matching = [event for event in events if event.kind == kind]
    return matching[-1] if matching else None


def _lease_for(leases: list[Lease], mac: str | None, ip: str | None) -> Lease | None:
    """The lease that actually belongs to this client. If both mac and ip
    are known but point at different leases (someone else is squatting on
    the client's expected address), that's a conflict for
    _reservation_conflict()/_root_cause_findings() to report explicitly -
    this must not silently attribute the other client's lease to ours."""
    if ip and not mac:
        return next((lease for lease in leases if lease.ip == ip), None)
    if mac:
        by_ip_and_mac = next((lease for lease in leases if lease.ip == ip and lease.mac == mac), None) if ip else None
        if by_ip_and_mac:
            return by_ip_and_mac
        matches = [lease for lease in leases if lease.mac == mac]
        active = next((lease for lease in matches if lease.is_active), None)
        return active or (matches[0] if matches else None)
    return None


def _subnet_label(subnet: Subnet) -> str:
    return f"{subnet.network}/{subnet.netmask}"


def normalize_mac(mac: str | None) -> str | None:
    if not mac:
        return None
    return mac.strip().lower().replace("-", ":") or None


def _identity_step(mac: str | None, ip: str | None, hostname: str | None, reservation: Host | None, lease: Lease | None) -> FlowStep:
    evidence = []
    if mac:
        evidence.append(Evidence(_("MAC address"), mac))
        vendor = lookup_vendor(mac)
        if vendor:
            evidence.append(Evidence(_("Vendor"), vendor))
    if ip:
        evidence.append(Evidence(_("IP address"), ip))
    known_hostname = hostname or (reservation.name if reservation else None) or (lease.hostname if lease else None)
    if known_hostname:
        evidence.append(Evidence(_("Hostname"), known_hostname))

    if not mac and not ip:
        return FlowStep(_("Client"), Status.UNKNOWN, _("No MAC address, IP address, or hostname was provided to identify this client."), evidence)
    return FlowStep(_("Client"), Status.HEALTHY if evidence else Status.UNKNOWN, _("Identified from the provided MAC/IP."), evidence)


def _activity_step(events: list[DhcpEvent], log_unavailable: str | None, logs_requests: bool) -> FlowStep:
    if log_unavailable:
        return FlowStep(_("DHCP activity"), Status.UNKNOWN, log_unavailable, [])
    if not events:
        detail = _("No DHCP protocol activity for this client was found in the log.")
        if not logs_requests:
            detail += " " + _("At its default INFO severity Kea logs only offers, allocations, releases and declines; DISCOVER, REQUEST and NAK appear only with debug logging.")
        return FlowStep(_("DHCP activity"), Status.UNKNOWN, detail, [])
    evidence = [Evidence(event.timestamp, event.raw) for event in events[-10:]]
    has_nak = any(event.kind == "DHCPNAK" for event in events)
    has_ack = any(event.kind == "DHCPACK" for event in events)
    status = Status.CRITICAL if has_nak and not has_ack else Status.HEALTHY if has_ack else Status.WARNING
    return FlowStep(_("DHCP activity"), status, _("1 matching log entry found.") if len(events) == 1 else _("{n} matching log entries found.", n=len(events)), evidence)


def _subnet_step(subnet: Subnet | None, ip: str | None, candidate_subnets: list[Subnet]) -> FlowStep:
    if subnet:
        return FlowStep(_("Subnet selection"), Status.HEALTHY, _("{value} covers this address.", value=_subnet_label(subnet)), [Evidence(_("Subnet"), _subnet_label(subnet))])
    if ip:
        return FlowStep(_("Subnet selection"), Status.CRITICAL, _("No configured subnet's network contains {ip}.", ip=ip), [Evidence(_("IP address"), ip)])
    if candidate_subnets:
        return FlowStep(
            _("Subnet selection"),
            Status.UNKNOWN,
            _("No IP is known yet, but the log shows this client's traffic arriving on an interface tagged to these subnet(s). Interface tags are organizational metadata, not a live directive, so this is a guess, not a fact."),
            [Evidence(_("Candidate subnet"), _subnet_label(s)) for s in candidate_subnets],
        )
    return FlowStep(_("Subnet selection"), Status.UNKNOWN, _("No IP address is known yet, so the subnet cannot be determined."), [])


def _reservation_step(reservation: Host | None, subnet: Subnet | None) -> FlowStep:
    if reservation:
        evidence = [Evidence(_("Reservation"), reservation.name), Evidence(_("Fixed address"), reservation.fixed_address or "(none)")]
        return FlowStep(_("Reservation lookup"), Status.HEALTHY, _("'{name}' reserves this MAC to {value}.", name=reservation.name, value=reservation.fixed_address or _("(no address set)")), evidence)
    return FlowStep(_("Reservation lookup"), Status.HEALTHY, _("No static reservation for this MAC - expected to use the dynamic pool."), [])


def _pool_step(subnet: Subnet | None) -> FlowStep:
    if subnet is None:
        return FlowStep(_("Pool selection"), Status.UNKNOWN, _("No subnet identified, so the pool cannot be determined."), [])
    if not pool_ranges(subnet):
        return FlowStep(_("Pool selection"), Status.CRITICAL, _("{value} has no pool range configured.", value=_subnet_label(subnet)), [])
    return FlowStep(_("Pool selection"), Status.HEALTHY, _("Pool range: {value}", value=pools_label(subnet)), [Evidence(_("range"), pools_label(subnet))])


def _reservation_conflict(reservation: Host | None, leases: list[Lease]) -> Lease | None:
    if not reservation or not reservation.fixed_address:
        return None
    return next(
        (lease for lease in leases if lease.ip == reservation.fixed_address and lease.is_active and lease.mac != reservation.mac),
        None,
    )


def _availability_step(subnet: Subnet | None, reservation: Host | None, leases: list[Lease]) -> FlowStep:
    if reservation and reservation.fixed_address:
        conflicting = _reservation_conflict(reservation, leases)
        if conflicting:
            return FlowStep(
                _("Address availability"),
                Status.CRITICAL,
                _("{fixed_address} is reserved for {mac}, but is currently actively leased to a different MAC ({mac2}).", fixed_address=reservation.fixed_address, mac=reservation.mac, mac2=conflicting.mac),
                [Evidence(_("Reserved to"), reservation.mac or ""), Evidence(_("Actually leased to"), conflicting.mac or "")],
            )
        return FlowStep(_("Address availability"), Status.HEALTHY, _("{fixed_address} is not held by any other active lease.", fixed_address=reservation.fixed_address), [])
    if subnet is None:
        return FlowStep(_("Address availability"), Status.UNKNOWN, _("No subnet identified, so pool availability cannot be checked."), [])
    used, total = subnet_utilization(subnet, leases)
    if total == 0:
        return FlowStep(_("Address availability"), Status.UNKNOWN, _("No pool range configured on this subnet."), [])
    status = Status.CRITICAL if used >= total else Status.HEALTHY
    return FlowStep(_("Address availability"), status, _("{used}/{total} pool addresses allocated.", used=used, total=total), [Evidence(_("Allocated"), str(used)), Evidence(_("Usable"), str(total))])


def _response_step(events: list[DhcpEvent]) -> FlowStep:
    nak = _most_recent(events, "DHCPNAK")
    ack = _most_recent(events, "DHCPACK")
    offer = _most_recent(events, "DHCPOFFER")
    discover = _most_recent(events, "DHCPDISCOVER")

    if nak and (ack is None or events.index(nak) > events.index(ack)):
        detail = _("The DHCP server sent DHCPNAK. Reason: {reason}.", reason=nak.reason) if nak.reason else _("The DHCP server sent DHCPNAK. No reason was recorded in the log.")
        return FlowStep(_("DHCP response"), Status.CRITICAL, detail, [Evidence(nak.timestamp, nak.raw)])
    if ack:
        return FlowStep(_("DHCP response"), Status.HEALTHY, _("The DHCP server sent DHCPACK."), [Evidence(ack.timestamp, ack.raw)])
    if discover and offer is None:
        detail = discover.reason or _("DHCPDISCOVER was logged but no matching DHCPOFFER followed.")
        return FlowStep(_("DHCP response"), Status.WARNING, detail, [Evidence(discover.timestamp, discover.raw)])
    if offer:
        return FlowStep(_("DHCP response"), Status.WARNING, _("The DHCP server offered an address, but no DHCPACK confirming it was found."), [Evidence(offer.timestamp, offer.raw)])
    return FlowStep(_("DHCP response"), Status.UNKNOWN, _("No DHCP response activity found in the log for this client."), [])


def _lease_step(lease: Lease | None) -> FlowStep:
    if lease is None:
        return FlowStep(_("Lease"), Status.UNKNOWN, _("No lease record exists for this client."), [])
    evidence = [
        Evidence(_("IP"), lease.ip),
        Evidence(_("State"), lease.binding_state or "unknown"),
        Evidence(_("Ends"), lease.ends or "unknown"),
    ]
    status = Status.HEALTHY if lease.is_active else Status.WARNING
    return FlowStep(_("Lease"), status, _("Lease state: {value}.", value=lease.binding_state or 'unknown'), evidence)


def _root_cause_findings(
    reservation: Host | None,
    subnet: Subnet | None,
    ip: str | None,
    lease: Lease | None,
    leases: list[Lease],
    events: list[DhcpEvent],
) -> list[Finding]:
    """Priority-ordered: the first applicable rule is reported as *the*
    root cause rather than piling on every symptom that shares one cause."""

    # 1. A reservation exists but its address is actively held by someone else.
    if reservation and reservation.fixed_address:
        conflicting = _reservation_conflict(reservation, leases)
        if conflicting:
            return [
                Finding(
                    status=Status.CRITICAL,
                    problem=_("Reserved address is in use by another client"),
                    root_cause=_("'{name}' is fixed to {fixed_address}, but that address is currently actively leased to {mac}, not {mac2}.", name=reservation.name, fixed_address=reservation.fixed_address, mac=conflicting.mac, mac2=reservation.mac),
                    confidence=Confidence.CONFIRMED,
                    evidence=[
                        Evidence(_("Reservation"), reservation.name),
                        Evidence(_("Reserved address"), reservation.fixed_address),
                        Evidence(_("Reserved to MAC"), reservation.mac or ""),
                        Evidence(_("Currently leased to MAC"), conflicting.mac or ""),
                    ],
                    impact=_("This client cannot obtain its reserved address until the conflicting lease is released or denied."),
                    actions=[Action(_("Edit reservation"), f"/reservations/{reservation.name}/edit"), Action(_("View leases"), "/leases")],
                )
            ]

    # 2. The log shows dhcpd explicitly rejecting this client.
    nak = _most_recent(events, "DHCPNAK")
    ack = _most_recent(events, "DHCPACK")
    if nak and (ack is None or events.index(nak) > events.index(ack)):
        return [
            Finding(
                status=Status.CRITICAL,
                problem=_("The DHCP server sent DHCPNAK"),
                root_cause=nak.reason or _("The DHCP server rejected this client's request; no reason text was recorded in the log."),
                confidence=Confidence.CONFIRMED if nak.reason else Confidence.STRONG,
                evidence=[Evidence(nak.timestamp, nak.raw)],
                impact=_("The client was denied the address it requested and must restart DHCP negotiation."),
                actions=[],
            )
        ]

    # 3. No reservation, and this client's subnet's pool is exhausted.
    if subnet and not reservation:
        pf = pool_finding(subnet, leases)
        if pf and pf.status == Status.CRITICAL and not (lease and lease.is_active):
            return [pf]

    # 4. We know an IP but no configured subnet covers it.
    if ip and subnet is None:
        return [
            Finding(
                status=Status.WARNING,
                problem=_("Address not covered by any configured subnet"),
                root_cause=_("No configured subnet contains {ip}.", ip=ip),
                confidence=Confidence.CONFIRMED,
                evidence=[Evidence(_("IP address"), ip)],
                impact=_("The DHCP server cannot serve this address at all under the current configuration."),
                actions=[Action(_("View subnets"), "/subnets")],
            )
        ]

    # 5. A DHCPDISCOVER was logged but nothing ever followed - possible, not confirmed.
    discover = _most_recent(events, "DHCPDISCOVER")
    offer = _most_recent(events, "DHCPOFFER")
    if discover and offer is None and not (lease and lease.is_active):
        reason = discover.reason
        return [
            Finding(
                status=Status.WARNING,
                problem=_("No DHCPOFFER followed this client's DHCPDISCOVER"),
                root_cause=(_("The DHCP server logged: {reason}", reason=reason) if reason else _("The DHCP server logged a DHCPDISCOVER from this client but never logged an offer - the underlying reason isn't recorded.")),
                confidence=Confidence.STRONG if reason else Confidence.POSSIBLE,
                evidence=[Evidence(discover.timestamp, discover.raw)],
                impact=_("This client did not receive an address on this attempt."),
                actions=[],
            )
        ]

    return []


def diagnose_client(
    config: DhcpdConfig,
    leases: list[Lease],
    events: list[DhcpEvent],
    log_unavailable: str | None,
    mac: str | None = None,
    ip: str | None = None,
    hostname: str | None = None,
    logs_requests: bool = True,
) -> DiagnosticResult:
    mac = normalize_mac(mac)

    reservation = _find_reservation_by_mac(config, mac) if mac else None
    if reservation is None and ip:
        reservation = _find_reservation_by_ip(config, ip)
        if reservation and mac is None:
            mac = reservation.mac

    if reservation and not ip:
        ip = reservation.fixed_address
    if reservation and mac is None:
        mac = reservation.mac

    lease = _lease_for(leases, mac, ip)
    if lease and mac is None:
        mac = lease.mac
    if lease and not ip:
        ip = lease.ip

    client_events = dhcp_log.events_for(events, mac, ip) if not log_unavailable else []

    subnet = find_containing_subnet(config, ip) if ip else None
    candidate_subnets: list[Subnet] = []
    if subnet is None and client_events:
        last_iface = next((e.iface for e in reversed(client_events) if e.iface), None)
        if last_iface:
            candidate_subnets = [s for s in config.subnets if get_subnet_interface(config, s) == last_iface]

    steps = [
        _identity_step(mac, ip, hostname, reservation, lease),
        _activity_step(client_events, log_unavailable, logs_requests),
        _subnet_step(subnet, ip, candidate_subnets),
        _reservation_step(reservation, subnet),
        _pool_step(subnet),
        _availability_step(subnet, reservation, leases),
        _response_step(client_events),
        _lease_step(lease),
    ]

    findings = _root_cause_findings(reservation, subnet, ip, lease, leases, client_events)

    if not findings:
        if lease and lease.is_active:
            findings.append(
                Finding(
                    status=Status.HEALTHY,
                    problem=_("Client has a valid, active lease"),
                    root_cause="",
                    confidence=Confidence.CONFIRMED,
                    evidence=[Evidence(_("IP"), lease.ip), Evidence(_("Ends"), lease.ends or "unknown")],
                )
            )
        elif mac is None and ip is None:
            findings.append(
                Finding(
                    status=Status.UNKNOWN,
                    problem=_("Insufficient evidence"),
                    root_cause=_("No MAC address, IP address, or hostname was provided, so no reservation, lease, or log activity could be checked."),
                    confidence=Confidence.UNKNOWN,
                    evidence=[],
                )
            )
        elif reservation is None and lease is None and not client_events:
            findings.append(
                Finding(
                    status=Status.UNKNOWN,
                    problem=_("Insufficient evidence"),
                    root_cause=_("No reservation, lease, or DHCP log activity matches this identifier."),
                    confidence=Confidence.UNKNOWN,
                    evidence=[Evidence(_("MAC"), mac or "unknown"), Evidence(_("IP"), ip or "unknown")],
                    impact=_("Cannot determine whether this client has ever attempted to obtain an address."),
                )
            )
        else:
            findings.append(
                Finding(
                    status=Status.UNKNOWN,
                    problem=_("No active lease, and no evidence of why"),
                    root_cause=(
                        _("A reservation and/or pool capacity exist for this client, but there is no active lease and no DHCP log activity explaining why - it may simply be offline, or have not requested an address recently.")
                    ),
                    confidence=Confidence.UNKNOWN,
                    evidence=[
                        Evidence(_("Reservation"), reservation.name if reservation else "(none)"),
                        Evidence(_("Lease"), lease.binding_state if lease else "(none)"),
                    ],
                    impact=_("Client cannot reach the network until it successfully requests and receives a lease."),
                    actions=[Action(_("View reservation"), f"/reservations/{reservation.name}/edit")] if reservation else [],
                )
            )

    description = mac or ip or hostname or _("unknown client")
    return DiagnosticResult(title=_("Client diagnostics"), target_description=description, findings=findings, steps=steps, resolved_mac=mac)
