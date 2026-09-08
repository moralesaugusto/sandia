from pathlib import Path

import pytest

from sandia.config import Settings
from sandia.diagnostics.models import Confidence, Status
from sandia.diagnostics.server import diagnose_server
from sandia.dhcpd import apply as apply_module

GOOD_CONF = "authoritative;\nsubnet 10.0.0.0 netmask 255.255.255.0 { range 10.0.0.10 10.0.0.20; }\n"
CLEAN_LOG = "Sep  2 09:15:00 host dhcpd[1]: DHCPACK on 10.0.0.10 to aa:aa:aa:aa:aa:01 via eth0\n"


@pytest.fixture
def settings(tmp_path):
    conf = tmp_path / "dhcpd.conf"
    conf.write_text(GOOD_CONF)
    leases = tmp_path / "dhcpd.leases"
    leases.write_text("")
    interfaces_conf = tmp_path / "isc-dhcp-server-defaults"
    interfaces_conf.write_text('INTERFACESv4="eth0"\n')
    log = tmp_path / "dhcpd.log"
    log.write_text(CLEAN_LOG)
    return Settings(
        data_dir=tmp_path / "data",
        dhcpd_conf_path=conf,
        leases_path=leases,
        backup_dir=tmp_path / "backups",
        interfaces_conf_path=interfaces_conf,
        dhcp_log_path=log,
    )


def _mock_run(monkeypatch, service_status="active", config_ok=True, config_missing=False):
    async def fake_run(*args):
        if args[:1] == ("dhcpd",):
            if config_missing:
                return apply_module.CommandResult(ok=False, stdout="", stderr="[Errno 2] No such file or directory: 'dhcpd'", command_missing=True)
            return apply_module.CommandResult(ok=config_ok, stdout="", stderr="" if config_ok else "syntax error near line 4")
        if args[:1] == ("systemctl",):
            if args[1] == "is-active":
                return apply_module.CommandResult(ok=service_status == "active", stdout=service_status, stderr="")
            return apply_module.CommandResult(ok=True, stdout="", stderr="")
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(apply_module, "_run", fake_run)


async def test_healthy_server(settings, monkeypatch):
    _mock_run(monkeypatch)
    result = await diagnose_server(settings)

    assert result.status == Status.HEALTHY
    assert result.findings[0].problem == "No issues detected"


async def test_stopped_service_is_critical(settings, monkeypatch):
    _mock_run(monkeypatch, service_status="inactive")
    result = await diagnose_server(settings)

    assert result.status == Status.CRITICAL
    finding = next(f for f in result.findings if "not running" in f.problem)
    assert finding.confidence == Confidence.CONFIRMED
    assert "inactive" in finding.evidence[0].value


async def test_invalid_configuration_is_critical(settings, monkeypatch):
    _mock_run(monkeypatch, config_ok=False)
    result = await diagnose_server(settings)

    assert result.status == Status.CRITICAL
    finding = next(f for f in result.findings if f.problem == "Live configuration is invalid")
    assert finding.confidence == Confidence.CONFIRMED
    assert "syntax error" in finding.evidence[0].value


async def test_lease_database_unreadable_is_warning(settings, monkeypatch):
    _mock_run(monkeypatch)

    original_read_text = Path.read_text

    def fake_read_text(self, *args, **kwargs):
        if self == settings.leases_path:
            raise PermissionError("denied")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fake_read_text)

    result = await diagnose_server(settings)

    assert result.status == Status.WARNING
    finding = next(f for f in result.findings if "not readable" in f.problem)
    assert finding.confidence == Confidence.CONFIRMED


async def test_missing_leases_file_is_warning(settings, monkeypatch):
    _mock_run(monkeypatch)
    settings.leases_path.unlink()

    result = await diagnose_server(settings)

    assert result.status == Status.WARNING
    assert any(f.problem == "Leases file not found" for f in result.findings)


async def test_no_interfaces_configured_is_warning(settings, monkeypatch):
    _mock_run(monkeypatch)
    settings.interfaces_conf_path.write_text('INTERFACESv4=""\n')

    result = await diagnose_server(settings)

    assert any(f.problem == "No interfaces configured" for f in result.findings)


async def test_diagnostic_command_failure_does_not_claim_config_is_invalid(settings, monkeypatch):
    # The dhcpd binary itself can't be run - this must NOT be reported the
    # same way as "we ran it and it found the config invalid".
    _mock_run(monkeypatch, config_missing=True)
    result = await diagnose_server(settings)

    finding = next(f for f in result.findings if "Could not validate" in f.problem)
    assert finding.status == Status.WARNING
    assert finding.confidence == Confidence.UNKNOWN
    assert not any(f.problem == "Live configuration is invalid" for f in result.findings)


async def test_dhcp_log_unavailable_is_warning_not_unknown_overall(settings, monkeypatch):
    _mock_run(monkeypatch)
    settings.dhcp_log_path.unlink()

    result = await diagnose_server(settings)

    finding = next(f for f in result.findings if f.problem == "DHCP log not available")
    assert finding.status == Status.WARNING
    assert finding.confidence == Confidence.CONFIRMED


async def test_recent_dhcp_errors_are_surfaced(settings, monkeypatch):
    _mock_run(monkeypatch)
    settings.dhcp_log_path.write_text(
        CLEAN_LOG + "Sep  2 10:00:00 host dhcpd[1]: Configuration file errors encountered -- exiting\n"
    )

    result = await diagnose_server(settings)

    finding = next(f for f in result.findings if "error-related keywords" in f.problem)
    assert finding.status == Status.WARNING
    assert finding.confidence == Confidence.CONFIRMED
    assert any("Configuration file errors" in e.value for e in finding.evidence)
