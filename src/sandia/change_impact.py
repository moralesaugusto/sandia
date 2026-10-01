"""What a config change does, computed before it is applied.

Pure functions over two parsed configs (live and proposed) and the current
leases - no I/O. Everything reported here is derived from that data; the
risk level is a fixed rule over the results, not a guess. The Review page
(routers/review.py) renders it, and the AI assistant may explain it but
never changes it.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field

from .dhcpd import DhcpdConfig, Host, Option, Parameter, Subnet
from .dhcpd.subnet_interface import get_subnet_interface
from .diagnostics import Finding, Status, finding_key, scan_config
from .diagnostics.subnet import HIGH_UTILIZATION_THRESHOLD
from .i18n import _
from .leases import Lease
from .utilization import (
    find_containing_subnet,
    in_pools,
    pool_ranges,
    pools_label,
    subnet_utilization,
)

RISK_LOW = "low"
RISK_REVIEW = "review"
RISK_HIGH = "high"


@dataclass
class ValueChange:
    name: str
    before: str
    after: str


@dataclass
class SubnetChange:
    key: str
    label: str
    kind: str  # "added", "removed" or "modified"
    pools_before: str = ""
    pools_after: str = ""
    capacity_before: int = 0
    capacity_after: int = 0
    active: int = 0
    settings: list[ValueChange] = field(default_factory=list)


@dataclass
class AffectedLease:
    ip: str
    mac: str | None
    hostname: str | None
    reason: str
    subnet_key: str | None


@dataclass
class ImpactFinding:
    finding: Finding
    introduced: bool


@dataclass
class Impact:
    risk: str
    risk_reasons: list[str]
    unchanged: bool
    subnet_changes: list[SubnetChange]
    global_changes: list[ValueChange]
    reservation_changes: list[ValueChange]
    interface_change: ValueChange | None
    affected_leases: list[AffectedLease]
    capacity_warnings: list[str]
    findings: list[ImpactFinding]
    summary: list[str]

    @property
    def introduced_findings(self) -> list[ImpactFinding]:
        return [f for f in self.findings if f.introduced]


def _label(subnet: Subnet) -> str:
    try:
        return str(ipaddress.ip_network(f"{subnet.network}/{subnet.netmask}", strict=False))
    except ValueError:
        return f"{subnet.network}/{subnet.netmask}"


def _settings(nodes: list) -> dict[str, str]:
    return {n.name: n.value for n in nodes if isinstance(n, (Parameter, Option)) and n.name != "range"}


def _value_changes(before: dict[str, str], after: dict[str, str]) -> list[ValueChange]:
    return [
        ValueChange(name, before.get(name, ""), after.get(name, ""))
        for name in sorted(before.keys() | after.keys())
        if before.get(name) != after.get(name)
    ]


def _is_deny(host: Host) -> bool:
    return host.get("deny") == "booting"


def _host_text(host: Host | None) -> str:
    if host is None:
        return ""
    if _is_deny(host):
        return _("deny {mac}", mac=host.mac or "?")
    return f"{host.mac or '?'} -> {host.fixed_address or '?'}"


def _reservation_changes(old: DhcpdConfig, new: DhcpdConfig) -> list[ValueChange]:
    before = {h.name: _host_text(h) for h in old.all_hosts}
    after = {h.name: _host_text(h) for h in new.all_hosts}
    return _value_changes(before, after)


def _subnet_changes(old: DhcpdConfig, new: DhcpdConfig, leases: list[Lease]) -> list[SubnetChange]:
    old_subnets = {s.key: s for s in old.subnets}
    new_subnets = {s.key: s for s in new.subnets}
    changes = []
    for key in [*old_subnets, *(k for k in new_subnets if k not in old_subnets)]:
        before, after = old_subnets.get(key), new_subnets.get(key)
        subnet = after or before
        change = SubnetChange(key=key, label=_label(subnet), kind="modified")
        if before:
            change.active, change.capacity_before = subnet_utilization(before, leases)
            change.pools_before = pools_label(before)
        if after:
            change.capacity_after = subnet_utilization(after, leases)[1]
            change.pools_after = pools_label(after)
        before_settings = _settings(before.body) if before else {}
        after_settings = _settings(after.body) if after else {}
        before_iface = get_subnet_interface(old, before) if before else None
        after_iface = get_subnet_interface(new, after) if after else None
        if before_iface != after_iface:
            before_settings["interface"], after_settings["interface"] = before_iface or "", after_iface or ""
        change.settings = _value_changes(before_settings, after_settings)
        if before is None:
            change.kind = "added"
        elif after is None:
            change.kind = "removed"
        elif change.pools_before == change.pools_after and not change.settings:
            continue
        changes.append(change)
    return changes


def _reserved_by_ip(config: DhcpdConfig) -> dict[str, Host]:
    reserved: dict[str, Host] = {}
    for host in config.all_hosts:
        if host.fixed_address and not _is_deny(host):
            reserved.setdefault(host.fixed_address, host)
    return reserved


def _denied_macs(config: DhcpdConfig) -> set[str]:
    return {h.mac.lower() for h in config.all_hosts if _is_deny(h) and h.mac}


def _served(config: DhcpdConfig, reserved: dict[str, Host], lease: Lease) -> bool:
    """Whether this config would keep serving the lease's address to its
    client: inside a pool of the subnet containing it, or reserved for it."""
    subnet = find_containing_subnet(config, lease.ip)
    if subnet is None:
        return False
    host = reserved.get(lease.ip)
    if host and host.mac:
        return bool(lease.mac) and host.mac.lower() == lease.mac.lower()
    return in_pools(pool_ranges(subnet), lease.ip)


def _affected_leases(old: DhcpdConfig, new: DhcpdConfig, leases: list[Lease]) -> list[AffectedLease]:
    new_keys = {s.key for s in new.subnets}
    newly_denied = _denied_macs(new) - _denied_macs(old)
    old_reserved, new_reserved = _reserved_by_ip(old), _reserved_by_ip(new)
    affected = []
    for lease in leases:
        if not lease.is_active:
            continue
        old_subnet = find_containing_subnet(old, lease.ip)
        new_subnet = find_containing_subnet(new, lease.ip)
        reason = None
        if lease.mac and lease.mac.lower() in newly_denied:
            reason = _("The client will be denied.")
        elif old_subnet and new_subnet is None:
            if old_subnet.key not in new_keys:
                reason = _("Its subnet {subnet} is removed.", subnet=_label(old_subnet))
            else:
                reason = _("The address is no longer inside any configured subnet.")
        elif _served(old, old_reserved, lease) and not _served(new, new_reserved, lease):
            host = new_reserved.get(lease.ip)
            if host and host.mac:
                reason = _("The address becomes reserved for another device ({mac}).", mac=host.mac)
            else:
                reason = _("The address leaves the pool; the lease will not be renewed and the client will get a new address.")
        if reason:
            subnet = new_subnet or old_subnet
            affected.append(AffectedLease(lease.ip, lease.mac, lease.hostname, reason, subnet.key if subnet and subnet.key in new_keys else None))
    return affected


def _capacity_warnings(changes: list[SubnetChange], new: DhcpdConfig, leases: list[Lease]) -> tuple[list[str], list[str]]:
    """(critical, warning) messages for subnets whose pools changed."""
    critical, warning = [], []
    for change in changes:
        if change.kind == "removed" or change.pools_before == change.pools_after:
            continue
        if change.capacity_after < change.active:
            critical.append(
                _("{subnet}: the new pools hold {capacity} addresses but {active} are leased now.", subnet=change.label, capacity=change.capacity_after, active=change.active)
            )
            continue
        used, total = subnet_utilization(new.find_subnet(change.key), leases)
        if total and used / total >= HIGH_UTILIZATION_THRESHOLD:
            warning.append(
                _("{subnet}: {used} of {total} pool addresses ({pct:.0f}%) would be in use - close to exhaustion.", subnet=change.label, used=used, total=total, pct=used / total * 100)
            )
    return critical, warning


def _seconds(value: str | None) -> str:
    return _("{value} s", value=value) if value else ""


def effective_summary(config: DhcpdConfig, leases: list[Lease], interfaces: list[str]) -> list[str]:
    """Plain-language description of what the config makes the server do."""
    lines = [
        _(
            "Global: {authoritative}; default lease {default}; max lease {maximum}; domain {domain}; DNS {dns}.",
            authoritative=_("authoritative") if config.get("authoritative") is not None else _("not authoritative"),
            default=_seconds(config.get("default-lease-time")) or _("server default"),
            maximum=_seconds(config.get("max-lease-time")) or _("server default"),
            domain=(config.get("domain-name") or "").strip('"') or _("none"),
            dns=config.get("domain-name-servers") or _("none"),
        ),
        _("Listening on: {interfaces}.", interfaces=", ".join(interfaces) or _("none")),
    ]
    for subnet in config.subnets:
        used, total = subnet_utilization(subnet, leases)
        iface = get_subnet_interface(config, subnet)
        pools = (
            _("hands out {pools} ({total} addresses, {used} in use)", pools=pools_label(subnet), total=total, used=used)
            if total
            else _("no dynamic pool (reservations only)")
        )
        parts = [pools]
        if subnet.get("routers"):
            parts.append(_("router {value}", value=subnet.get("routers")))
        if subnet.get("domain-name-servers"):
            parts.append(_("DNS {value}", value=subnet.get("domain-name-servers")))
        if subnet.get("default-lease-time"):
            parts.append(_("lease {value}", value=_seconds(subnet.get("default-lease-time"))))
        reservations = [h for h in subnet.hosts if not _is_deny(h)]
        parts.append(_("{count} reservation(s)", count=len(reservations)))
        where = f"{_label(subnet)} ({iface})" if iface else _label(subnet)
        lines.append(f"{where}: " + "; ".join(parts) + ".")
    reservations = [h for h in config.top_level_hosts if not _is_deny(h)]
    denied = [h for h in config.all_hosts if _is_deny(h)]
    if reservations:
        lines.append(_("{count} global reservation(s).", count=len(reservations)))
    if denied:
        lines.append(_("{count} denied client(s).", count=len(denied)))
    return lines


def analyze(
    old: DhcpdConfig,
    new: DhcpdConfig,
    leases: list[Lease],
    old_interfaces: list[str],
    new_interfaces: list[str],
) -> Impact:
    subnet_changes = _subnet_changes(old, new, leases)
    global_changes = _value_changes(_settings(old.nodes), _settings(new.nodes))
    reservation_changes = _reservation_changes(old, new)
    interface_change = (
        ValueChange(_("listening interfaces"), ", ".join(old_interfaces), ", ".join(new_interfaces)) if old_interfaces != new_interfaces else None
    )
    affected = _affected_leases(old, new, leases)
    capacity_critical, capacity_warning = _capacity_warnings(subnet_changes, new, leases)

    before_keys = {finding_key(f) for f in scan_config(old, leases, old_interfaces)}
    findings = [ImpactFinding(f, finding_key(f) not in before_keys) for f in scan_config(new, leases, new_interfaces)]
    findings.sort(key=lambda f: not f.introduced)
    introduced = [f.finding for f in findings if f.introduced]

    unchanged = not (subnet_changes or global_changes or reservation_changes or interface_change)
    high, review = [], []
    if any(f.status == Status.CRITICAL for f in introduced):
        high.append(_("The change introduces a critical configuration anomaly."))
    if affected:
        high.append(_("{count} active lease(s) are affected.", count=len(affected)))
    high.extend(capacity_critical)
    if any(c.kind == "removed" and c.active for c in subnet_changes):
        high.append(_("A subnet with active leases is removed."))
    if any(f.status == Status.WARNING for f in introduced):
        review.append(_("The change introduces a warning."))
    review.extend(capacity_warning)
    if any(c.kind != "added" for c in subnet_changes):
        review.append(_("Existing subnets, pools or subnet options change."))
    if global_changes:
        review.append(_("Global settings change."))
    if interface_change:
        review.append(_("The listening interfaces change."))
    if any(c.before for c in reservation_changes):
        review.append(_("Existing reservations change or are removed."))

    if high:
        risk, reasons = RISK_HIGH, high + review
    elif review:
        risk, reasons = RISK_REVIEW, review
    else:
        risk = RISK_LOW
        reasons = [_("No change to the effective DHCP configuration (formatting or comments only).")] if unchanged else [_("Only additions, with no anomaly introduced and no active lease affected.")]

    return Impact(
        risk=risk,
        risk_reasons=reasons,
        unchanged=unchanged,
        subnet_changes=subnet_changes,
        global_changes=global_changes,
        reservation_changes=reservation_changes,
        interface_change=interface_change,
        affected_leases=affected,
        capacity_warnings=capacity_critical + capacity_warning,
        findings=findings,
        summary=effective_summary(new, leases, new_interfaces),
    )


def impact_as_text(impact: Impact) -> str:
    """The impact as plain text, for the AI assistant's context."""
    lines = [f"Risk: {impact.risk}", *(f"- {reason}" for reason in impact.risk_reasons), "", "Effective behavior after the change:"]
    lines += [f"- {line}" for line in impact.summary]
    if impact.subnet_changes:
        lines += ["", "Subnet changes:"]
        for c in impact.subnet_changes:
            lines.append(f"- {c.label} {c.kind}: pools '{c.pools_before}' -> '{c.pools_after}', capacity {c.capacity_before} -> {c.capacity_after}, active {c.active}")
            lines += [f"  - {v.name}: '{v.before}' -> '{v.after}'" for v in c.settings]
    for title, values in (("Global setting changes:", impact.global_changes), ("Reservation changes:", impact.reservation_changes)):
        if values:
            lines += ["", title, *(f"- {v.name}: '{v.before}' -> '{v.after}'" for v in values)]
    if impact.interface_change:
        lines += ["", f"Listening interfaces: '{impact.interface_change.before}' -> '{impact.interface_change.after}'"]
    if impact.affected_leases:
        lines += ["", "Affected active leases:"]
        lines += [f"- {a.ip} {a.mac or '-'} {a.hostname or '-'}: {a.reason}" for a in impact.affected_leases]
    if impact.findings:
        lines += ["", "Anomalies (from deterministic rules):"]
        for item in impact.findings:
            f = item.finding
            origin = "introduced by this change" if item.introduced else "already present"
            kind = "runtime observation" if f.runtime else "configuration"
            evidence = "; ".join(f"{e.label}: {e.value}" for e in f.evidence)
            lines.append(f"- [{f.status.value}, {kind}, {origin}] {f.problem}. {f.root_cause} Evidence: {evidence}")
    return "\n".join(lines)
