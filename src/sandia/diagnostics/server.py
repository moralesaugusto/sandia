"""Server-level checks: is isc-dhcp-server actually able to run at all."""

from __future__ import annotations

from ..config import Settings
from ..config_store import load_live_config
from ..dhcpd import apply as apply_module
from ..interfaces_conf import read_configured_interfaces
from . import dhcp_log
from .models import Action, Confidence, DiagnosticResult, Evidence, Finding, Status


async def _service_finding(settings: Settings) -> Finding | None:
    status = await apply_module.service_status(settings)
    if status == "active":
        return None
    return Finding(
        status=Status.CRITICAL,
        problem="isc-dhcp-server is not running",
        root_cause=f"systemctl reports the service as '{status}'.",
        confidence=Confidence.CONFIRMED,
        evidence=[Evidence("Service status", status), Evidence("Service name", settings.service_name)],
        impact="No client can obtain or renew a lease while the service is not active.",
        actions=[Action("View service page", "/service")],
    )


async def _config_finding(settings: Settings) -> Finding | None:
    result = await apply_module.check_live_config(settings)
    if result.ok:
        return None
    if result.command_missing:
        return Finding(
            status=Status.WARNING,
            problem="Could not validate the live configuration",
            root_cause=f"The `dhcpd` command could not be run ({result.stderr}), so config validity is unknown.",
            confidence=Confidence.UNKNOWN,
            evidence=[Evidence("dhcpd -t error", result.stderr)],
            impact="Configuration correctness cannot currently be confirmed by this check.",
            actions=[Action("View raw config", "/config/raw")],
        )
    return Finding(
        status=Status.CRITICAL,
        problem="Live configuration is invalid",
        root_cause="`dhcpd -t` failed against the configuration file currently on disk.",
        confidence=Confidence.CONFIRMED,
        evidence=[Evidence("dhcpd -t output", (result.stderr or result.stdout).strip())],
        impact="dhcpd is either running on a stale configuration or will fail to start/restart.",
        actions=[Action("View raw config", "/config/raw"), Action("View backups", "/backups")],
    )


def _leases_finding(settings: Settings) -> Finding | None:
    if not settings.leases_path.exists():
        return Finding(
            status=Status.WARNING,
            problem="Leases file not found",
            root_cause=f"No file exists at {settings.leases_path}.",
            confidence=Confidence.CONFIRMED,
            evidence=[Evidence("Leases path", str(settings.leases_path))],
            impact="Sandia cannot show current leases until the file exists (dhcpd creates it on first run).",
            actions=[],
        )
    try:
        settings.leases_path.read_text()
    except OSError as exc:
        return Finding(
            status=Status.WARNING,
            problem="Leases file is not readable",
            root_cause=str(exc),
            confidence=Confidence.CONFIRMED,
            evidence=[Evidence("Leases path", str(settings.leases_path))],
            impact="Sandia cannot show current leases or diagnose pool/client state until this is fixed.",
            actions=[],
        )
    return None


def _interfaces_finding(settings: Settings) -> Finding | None:
    interfaces = read_configured_interfaces(settings.interfaces_conf_path)
    if interfaces:
        return None
    return Finding(
        status=Status.WARNING,
        problem="No interfaces configured",
        root_cause=f"INTERFACESv4 in {settings.interfaces_conf_path} is empty or unset.",
        confidence=Confidence.CONFIRMED,
        evidence=[Evidence("INTERFACESv4", "(empty)")],
        impact="isc-dhcp-server may listen on every interface (default) or none, depending on your init system - verify this is intentional.",
        actions=[Action("View interfaces", "/interfaces")],
    )


def _recent_errors_finding(events: list) -> Finding | None:
    error_lines = dhcp_log.error_like_lines(events)
    if not error_lines:
        return None
    return Finding(
        status=Status.WARNING,
        problem=f"{len(error_lines)} recent DHCP log line(s) matched error-related keywords",
        root_cause="These log lines contain error/failure-related wording - review them below to determine the underlying cause.",
        confidence=Confidence.CONFIRMED,
        evidence=[Evidence(event.timestamp, event.raw) for event in error_lines],
        impact="May indicate a recurring problem serving some clients.",
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
                problem="DHCP log not available",
                root_cause=log_unavailable,
                confidence=Confidence.CONFIRMED,
                evidence=[Evidence("Configured log path", str(settings.dhcp_log_path))],
                impact="Recent DHCP protocol activity (offers, NAKs, declines) cannot be checked here or in client diagnostics.",
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
                problem="No issues detected",
                root_cause="",
                confidence=Confidence.CONFIRMED,
                evidence=[
                    Evidence("Service", "active"),
                    Evidence("Configuration", "valid"),
                    Evidence("Subnets", str(len(config.subnets))),
                    Evidence("Reservations", str(len(config.all_hosts))),
                ],
            )
        ]

    return DiagnosticResult(title="Server diagnostics", target_description=settings.service_name, findings=findings)
