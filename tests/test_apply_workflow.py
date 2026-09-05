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
        return apply_module.CommandResult(ok=True, stdout="ok", stderr="")

    monkeypatch.setattr(apply_module, "_run", fake_run)

    result = await apply_module.apply_new_config(settings, "authoritative;\n")

    assert result.ok
    assert settings.staging_path.read_text() == "authoritative;\n"
    assert settings.dhcpd_conf_path.read_text() == "authoritative;\n"
    assert calls == [("dhcpd", "-t", "-cf", str(settings.staging_path))]


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
        return apply_module.CommandResult(ok=True, stdout="", stderr="")

    monkeypatch.setattr(apply_module, "_run", fake_run)

    result = await apply_module.apply_new_config(settings, "new config\n")

    assert result.ok
    assert settings.dhcpd_conf_path.read_text() == "new config\n"
    backups = list(settings.backup_dir.glob("dhcpd.conf.*"))
    assert len(backups) == 1
    assert backups[0].read_text() == "old config\n"


async def test_apply_new_config_reports_install_failure_cleanly(settings, monkeypatch):
    async def fake_run(*args):
        return apply_module.CommandResult(ok=True, stdout="", stderr="")

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
