"""Server-level checks: is the DHCP server actually able to run at all."""

from __future__ import annotations

from ..config import Settings
from ..config_store import load_live_config
from ..dhcpd import apply as apply_module
from ..dhcpd import kea
from ..dhcpd.backend import get_backend, live_config_text
from ..dhcpd.parser import ParseError
from ..i18n import _
from ..interfaces_conf import read_configured_interfaces
from . import dhcp_log
from .models import Action, Confidence, DiagnosticResult, Evidence, Finding, Status


async def _service_finding(settings: Settings) -> Finding | None:
    status = await apply_module.service_status(settings)
    if status == "active":
        return None
    return Finding(
        status=Status.CRITICAL,
        problem=_("{service} is not running", service=get_backend(settings).label),
        root_cause=_("systemctl reports the service as '{status}'.", status=status),
        confidence=Confidence.CONFIRMED,
        evidence=[Evidence(_("Service status"), status), Evidence(_("Service name"), settings.service_name)],
        impact=_("No client can obtain or renew a lease while the service is not active."),
        actions=[Action(_("View service page"), "/service")],
    )


async def _config_finding(settings: Settings) -> Finding | None:
    result = await apply_module.check_live_config(settings)
    if result.ok:
        return None
    validator = get_backend(settings).validator
    if result.command_missing:
        return Finding(
            status=Status.WARNING,
            problem=_("Could not validate the live configuration"),
            root_cause=_("The `{validator}` command could not be run ({stderr}), so config validity is unknown.", validator=validator, stderr=result.stderr),
            confidence=Confidence.UNKNOWN,
            evidence=[Evidence(_("{validator} -t error", validator=validator), result.stderr)],
            impact=_("Configuration correctness cannot currently be confirmed by this check."),
            actions=[Action(_("View raw config"), "/config/raw")],
        )
    return Finding(
        status=Status.CRITICAL,
        problem=_("Live configuration is invalid"),
        root_cause=_("`{validator} -t` failed against the configuration file currently on disk.", validator=validator),
        confidence=Confidence.CONFIRMED,
        evidence=[Evidence(_("{validator} -t output", validator=validator), (result.stderr or result.stdout).strip())],
        impact=_("{validator} is either running on a stale configuration or will fail to start/restart.", validator=validator),
        actions=[Action(_("View raw config"), "/config/raw"), Action(_("View backups"), "/backups")],
    )


def _leases_finding(settings: Settings) -> Finding | None:
    if not settings.leases_path.exists():
        return Finding(
            status=Status.WARNING,
            problem=_("Leases file not found"),
            root_cause=_("No file exists at {leases_path}.", leases_path=settings.leases_path),
            confidence=Confidence.CONFIRMED,
            evidence=[Evidence(_("Leases path"), str(settings.leases_path))],
            impact=_("Sandia cannot show current leases until the file exists ({daemon} creates it on first run).", daemon=get_backend(settings).validator),
            actions=[],
        )
    try:
        settings.leases_path.read_text()
    except OSError as exc:
        return Finding(
            status=Status.WARNING,
            problem=_("Leases file is not readable"),
            root_cause=str(exc),
            confidence=Confidence.CONFIRMED,
            evidence=[Evidence(_("Leases path"), str(settings.leases_path))],
            impact=_("Sandia cannot show current leases or diagnose pool/client state until this is fixed."),
            actions=[],
        )
    return None


def _kea_interfaces_finding(settings: Settings) -> Finding | None:
    try:
        interfaces = kea.configured_interfaces(live_config_text(settings) or "{}")
    except ParseError:
        return None  # an unreadable config is already reported by the validation check
    if interfaces:
        return None
    return Finding(
        status=Status.WARNING,
        problem=_("No interfaces configured"),
        root_cause=_("Dhcp4.interfaces-config.interfaces in {path} is empty.", path=settings.dhcpd_conf_path),
        confidence=Confidence.CONFIRMED,
        evidence=[Evidence("interfaces-config", "(empty)")],
        impact=_("Kea does not listen on any interface until at least one is listed (or \"*\" for all)."),
        actions=[Action(_("View raw config"), "/config/raw")],
    )


def _interfaces_finding(settings: Settings) -> Finding | None:
    if get_backend(settings).name == "kea":
        return _kea_interfaces_finding(settings)
    interfaces = read_configured_interfaces(settings.interfaces_conf_path)
    if interfaces:
        return None
    return Finding(
        status=Status.WARNING,
        problem=_("No interfaces configured"),
        root_cause=_("INTERFACESv4 in {interfaces_conf_path} is empty or unset.", interfaces_conf_path=settings.interfaces_conf_path),
        confidence=Confidence.CONFIRMED,
        evidence=[Evidence(_("INTERFACESv4"), "(empty)")],
        impact=_("isc-dhcp-server may listen on every interface (default) or none, depending on your init system - verify this is intentional."),
        actions=[Action(_("View interfaces"), "/interfaces")],
    )


def _recent_errors_finding(events: list) -> Finding | None:
    error_lines = dhcp_log.error_like_lines(events)
    if not error_lines:
        return None
    return Finding(
        status=Status.WARNING,
        problem=_("{value} recent DHCP log line(s) matched error-related keywords", value=len(error_lines)),
        root_cause=_("These log lines contain error/failure-related wording - review them below to determine the underlying cause."),
        confidence=Confidence.CONFIRMED,
        evidence=[Evidence(event.timestamp, event.raw) for event in error_lines],
        impact=_("May indicate a recurring problem serving some clients."),
        actions=[],
    )


async def diagnose_server(settings: Settings) -> DiagnosticResult:
    findings: list[Finding] = []

    service_finding = await _service_finding(settings)
    if service_finding:
        findings.append(service_finding)

    config_finding = await _config_finding(settings)
    if config_finding:
        findings.append(config_finding)

    leases_finding = _leases_finding(settings)
    if leases_finding:
        findings.append(leases_finding)

    interfaces_finding = _interfaces_finding(settings)
    if interfaces_finding:
        findings.append(interfaces_finding)

    events, log_unavailable = dhcp_log.load_dhcp_events(settings)
    if log_unavailable:
        # A missing/unreadable log is an actionable gap (grant read access,
        # or set SANDIA_DHCP_LOG_PATH), not evidence the server itself is
        # unhealthy - Warning, not Unknown, so it doesn't drown out an
        # otherwise-confirmed-healthy service/config/leases/interfaces state.
        findings.append(
            Finding(
                status=Status.WARNING,
                problem=_("DHCP log not available"),
                root_cause=log_unavailable,
                confidence=Confidence.CONFIRMED,
                evidence=[Evidence(_("Configured log path"), dhcp_log.log_source_label(settings))],
                impact=_("Recent DHCP protocol activity (offers, NAKs, declines) cannot be checked here or in client diagnostics."),
                actions=[],
            )
        )
    else:
        recent_errors = _recent_errors_finding(events)
        if recent_errors:
            findings.append(recent_errors)

    if not any(f.status in (Status.CRITICAL, Status.WARNING) for f in findings):
        config = load_live_config(settings)
        findings = [
            Finding(
                status=Status.HEALTHY,
                problem=_("No issues detected"),
                root_cause="",
                confidence=Confidence.CONFIRMED,
                evidence=[
                    Evidence(_("Service"), "active"),
                    Evidence(_("Configuration"), "valid"),
                    Evidence(_("Subnets"), str(len(config.subnets))),
                    Evidence(_("Reservations"), str(len(config.all_hosts))),
                ],
            )
        ]

    return DiagnosticResult(title=_("Server diagnostics"), target_description=settings.service_name, findings=findings)
