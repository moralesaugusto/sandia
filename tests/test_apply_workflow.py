import pytest

from sandia.config import Settings
from sandia.dhcpd import apply as apply_module


@pytest.fixture
def settings(tmp_path):
    return Settings(
        data_dir=tmp_path / "data",
        dhcpd_conf_path=tmp_path / "dhcpd.conf",
        backup_dir=tmp_path / "backups",
    )


async def test_apply_new_config_success(settings, monkeypatch):
    calls = []

    async def fake_run(*args):
        calls.append(args)
        return apply_module.CommandResult(ok=True, stdout="active", stderr="")

    monkeypatch.setattr(apply_module, "_run", fake_run)

    result = await apply_module.apply_new_config(settings, "authoritative;\n")

    assert result.ok
    assert settings.staging_path.read_text() == "authoritative;\n"
    assert settings.dhcpd_conf_path.read_text() == "authoritative;\n"
    assert calls == [
        ("dhcpd", "-t", "-cf", str(settings.staging_path)),
        ("systemctl", "restart", settings.service_name),
        ("systemctl", "is-active", settings.service_name),
    ]


async def test_apply_new_config_stops_when_check_fails(settings, monkeypatch):
    async def fake_run(*args):
        return apply_module.CommandResult(ok=False, stdout="", stderr="syntax error")

    monkeypatch.setattr(apply_module, "_run", fake_run)

    result = await apply_module.apply_new_config(settings, "bad config")

    assert not result.ok
    assert result.stage == "check"
    assert result.output == "syntax error"
    assert not settings.dhcpd_conf_path.exists()  # live file untouched


async def test_apply_new_config_backs_up_existing_config(settings, monkeypatch):
    settings.dhcpd_conf_path.write_text("old config\n")

    async def fake_run(*args):
        return apply_module.CommandResult(ok=True, stdout="active", stderr="")

    monkeypatch.setattr(apply_module, "_run", fake_run)

    result = await apply_module.apply_new_config(settings, "new config\n")

    assert result.ok
    assert settings.dhcpd_conf_path.read_text() == "new config\n"
    backups = list(settings.backup_dir.glob("dhcpd.conf.*"))
    assert len(backups) == 1
    assert backups[0].read_text() == "old config\n"


async def test_install_is_atomic_and_preserves_file_mode(settings, monkeypatch):
    settings.dhcpd_conf_path.write_text("old config\n")
    settings.dhcpd_conf_path.chmod(0o640)

    async def fake_run(*args):
        return apply_module.CommandResult(ok=True, stdout="active", stderr="")

    monkeypatch.setattr(apply_module, "_run", fake_run)

    result = await apply_module.apply_new_config(settings, "new config\n")

    assert result.ok
    assert settings.dhcpd_conf_path.stat().st_mode & 0o777 == 0o640
    assert not list(settings.dhcpd_conf_path.parent.glob("*.sandia-tmp"))


def _fake_systemctl(restart_results: list[bool], status: str = "active"):
    """dhcpd -t always passes; each `systemctl restart` pops the next
    result from restart_results."""

    async def fake_run(*args):
        if args[:2] == ("systemctl", "restart"):
            ok = restart_results.pop(0)
            return apply_module.CommandResult(ok=ok, stdout="", stderr="" if ok else "Job failed")
        if args[:2] == ("systemctl", "is-active"):
            return apply_module.CommandResult(ok=status == "active", stdout=status, stderr="")
        return apply_module.CommandResult(ok=True, stdout="", stderr="")

    return fake_run


async def test_failed_restart_rolls_back_to_previous_config(settings, monkeypatch):
    settings.dhcpd_conf_path.write_text("old config\n")
    monkeypatch.setattr(apply_module, "_run", _fake_systemctl([False, True]))

    result = await apply_module.apply_new_config(settings, "new config\n")

    assert not result.ok
    assert result.stage == "restart"
    assert "Job failed" in result.output
    assert "Rolled back" in result.output
    assert "running again" in result.output
    assert settings.dhcpd_conf_path.read_text() == "old config\n"


async def test_inactive_service_after_restart_rolls_back(settings, monkeypatch):
    settings.dhcpd_conf_path.write_text("old config\n")
    monkeypatch.setattr(apply_module, "_run", _fake_systemctl([True, True], status="failed"))

    result = await apply_module.apply_new_config(settings, "new config\n")

    assert not result.ok
    assert result.stage == "restart"
    assert "'failed' after restart" in result.output
    assert "still failed" in result.output  # the rollback restart didn't come up either
    assert settings.dhcpd_conf_path.read_text() == "old config\n"


async def test_failed_restart_on_first_install_reports_no_rollback(settings, monkeypatch):
    monkeypatch.setattr(apply_module, "_run", _fake_systemctl([False]))

    result = await apply_module.apply_new_config(settings, "new config\n")

    assert not result.ok
    assert result.stage == "restart"
    assert "no previous config to roll back to" in result.output
    assert settings.dhcpd_conf_path.read_text() == "new config\n"


async def test_apply_new_config_reports_install_failure_cleanly(settings, monkeypatch):
    async def fake_run(*args):
        return apply_module.CommandResult(ok=True, stdout="active", stderr="")

    monkeypatch.setattr(apply_module, "_run", fake_run)

    def fake_copyfile(*args, **kwargs):
        raise PermissionError("[Errno 13] Permission denied")

    monkeypatch.setattr(apply_module.shutil, "copyfile", fake_copyfile)

    result = await apply_module.apply_new_config(settings, "authoritative;\n")

    assert not result.ok
    assert result.stage == "apply"
    assert "Permission denied" in result.output


async def test_run_returns_clean_failure_when_binary_missing():
    result = await apply_module._run("this-binary-does-not-exist-xyz")

    assert not result.ok
    assert result.stderr
    assert result.command_missing is True


async def test_check_live_config_validates_the_file_on_disk_not_staging(settings, monkeypatch):
    settings.dhcpd_conf_path.write_text("authoritative;\n")

    calls = []

    async def fake_run(*args):
        calls.append(args)
        return apply_module.CommandResult(ok=True, stdout="", stderr="")

    monkeypatch.setattr(apply_module, "_run", fake_run)

    result = await apply_module.check_live_config(settings)

    assert result.ok
    assert calls == [("dhcpd", "-t", "-cf", str(settings.dhcpd_conf_path))]


async def test_check_live_config_reports_missing_file_without_running_dhcpd(settings, monkeypatch):
    calls = []

    async def fake_run(*args):
        calls.append(args)
        return apply_module.CommandResult(ok=True, stdout="", stderr="")

    monkeypatch.setattr(apply_module, "_run", fake_run)

    result = await apply_module.check_live_config(settings)

    assert not result.ok
    assert "does not exist" in result.stderr
    assert calls == []  # never shelled out for a file that isn't there


async def test_check_live_config_skips_validation_in_dummy_mode(tmp_path):
    dummy_settings = Settings(data_dir=tmp_path / "data", dummy_data=True)
    result = await apply_module.check_live_config(dummy_settings)
    assert result.ok
