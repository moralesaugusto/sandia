import asyncio
from pathlib import Path

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
    assert settings.dhcpd_conf_path.read_text() == "authoritative;\n"
    check, *rest = calls
    assert check[:3] == ("dhcpd", "-t", "-cf")
    assert Path(check[3]).parent == settings.staging_dir
    assert Path(check[3]).name.startswith(".sandia-staged-")
    assert rest == [
        ("systemctl", "restart", settings.service_name),
        ("systemctl", "is-active", settings.service_name),
    ]
    assert not list(settings.staging_dir.glob(".sandia-staged-*"))  # staged file was installed, not left behind


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
    assert not list(settings.staging_dir.glob(".sandia-*"))


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

    def fake_replace(*args, **kwargs):
        raise PermissionError("[Errno 13] Permission denied")

    monkeypatch.setattr(apply_module.os, "replace", fake_replace)

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


# --- SEC-2026-02: serialized, private staging ------------------------------


async def test_validate_text_uses_a_private_staging_file_and_removes_it(settings, monkeypatch):
    seen = []

    async def fake_run(*args):
        path = Path(args[-1])
        seen.append((path, path.read_text(), path.stat().st_mode & 0o777))
        return apply_module.CommandResult(ok=True, stdout="", stderr="")

    monkeypatch.setattr(apply_module, "_run", fake_run)

    first, second = await asyncio.gather(
        apply_module.validate_text(settings, "one;\n"),
        apply_module.validate_text(settings, "two;\n"),
    )

    assert first.ok and second.ok
    assert seen[0][0] != seen[1][0]
    assert sorted(text for _, text, _ in seen) == ["one;\n", "two;\n"]
    assert all(mode == 0o600 for *_, mode in seen)
    assert not list(settings.staging_dir.glob(".sandia-staged-*"))


async def test_validated_file_is_the_one_installed(settings, monkeypatch):
    # Overwriting the old fixed staging path mid-validation used to change
    # what got installed. Now nothing else can reach the staged file.
    async def fake_run(*args):
        if args[0] == "dhcpd":
            (settings.staging_dir / ".sandia-staged.conf").write_text("planted;\n")
        return apply_module.CommandResult(ok=True, stdout="active", stderr="")

    monkeypatch.setattr(apply_module, "_run", fake_run)

    result = await apply_module.apply_new_config(settings, "validated;\n")

    assert result.ok
    assert settings.dhcpd_conf_path.read_text() == "validated;\n"


async def test_refuses_a_config_directory_writable_by_others(settings, monkeypatch):
    monkeypatch.setattr(apply_module, "_run", _fake_systemctl([True]))
    settings.staging_dir.chmod(0o777)
    try:
        result = await apply_module.apply_new_config(settings, "new config\n")
        checked = await apply_module.validate_text(settings, "new config\n")
    finally:
        settings.staging_dir.chmod(0o700)

    assert (result.ok, result.stage) == (False, "apply")
    assert "not writable by group or others" in result.output
    assert not checked.ok and "not writable by group or others" in checked.stderr
    assert not settings.dhcpd_conf_path.exists()


async def test_backup_never_follows_a_planted_symlink(settings, monkeypatch, tmp_path):
    settings.dhcpd_conf_path.write_text("old config\n")
    settings.backup_dir.mkdir()
    victim = tmp_path / "victim"
    victim.write_text("untouched\n")

    class FixedTime:
        @staticmethod
        def now():
            from datetime import datetime

            return datetime(2026, 10, 6, 12, 0, 0)

    monkeypatch.setattr(apply_module, "datetime", FixedTime)
    (settings.backup_dir / "dhcpd.conf.20261006-120000000000").symlink_to(victim)
    monkeypatch.setattr(apply_module, "_run", _fake_systemctl([True]))

    result = await apply_module.apply_new_config(settings, "new config\n")

    assert (result.ok, result.stage) == (False, "apply")
    assert victim.read_text() == "untouched\n"
    assert settings.dhcpd_conf_path.read_text() == "old config\n"
