from pathlib import Path

from sandia.config import Settings


def test_defaults():
    settings = Settings()
    assert settings.host == "0.0.0.0"
    assert settings.port == 7001
    assert settings.enable_https is True


def test_https_can_be_disabled(monkeypatch):
    monkeypatch.setenv("SANDIA_HTTPS", "0")
    assert Settings().enable_https is False


def test_https_enabled_for_other_values(monkeypatch):
    monkeypatch.setenv("SANDIA_HTTPS", "1")
    assert Settings().enable_https is True


def test_dummy_data_env_var_needs_no_other_configuration(monkeypatch, tmp_path):
    # Regression test: dummy mode must be fully self-contained from just
    # SANDIA_DUMMY_DATA=1 - it must not still require SANDIA_DATA_DIR to
    # avoid the /var/lib/sandia permission error.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("SANDIA_DUMMY_DATA", "1")
    monkeypatch.delenv("SANDIA_DATA_DIR", raising=False)

    settings = Settings()

    assert settings.data_dir == tmp_path / ".local" / "share" / "sandia-dummy"
    assert settings.data_dir != Path("/var/lib/sandia")


def test_explicit_data_dir_env_var_still_wins_in_dummy_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("SANDIA_DUMMY_DATA", "1")
    monkeypatch.setenv("SANDIA_DATA_DIR", str(tmp_path / "explicit"))

    settings = Settings()

    assert settings.data_dir == tmp_path / "explicit"
