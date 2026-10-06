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


def test_plain_http_defaults_to_loopback(monkeypatch):
    monkeypatch.setenv("SANDIA_HTTPS", "0")
    monkeypatch.delenv("SANDIA_HOST", raising=False)
    assert Settings().host == "127.0.0.1"
    monkeypatch.setenv("SANDIA_HOST", "0.0.0.0")
    assert Settings().host == "0.0.0.0"


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


def test_staging_dir_is_colocated_with_dhcpd_conf_not_data_dir(tmp_path):
    # Regression test: the isc-dhcp-server AppArmor profile Debian/Ubuntu
    # ship (/etc/apparmor.d/usr.sbin.dhcpd) only grants dhcpd read access to
    # /etc/dhcp/** (and a few other fixed paths) - not /var/lib/sandia/. If
    # the staging file Sandia validates with `dhcpd -t` lived under
    # data_dir, that check fails with a permission error enforced by
    # AppArmor's mandatory access control, which root does not bypass -
    # even when Sandia itself runs as root. So staging_dir must always be
    # the directory of dhcpd_conf_path, never under data_dir.
    settings = Settings(
        data_dir=tmp_path / "data",
        dhcpd_conf_path=tmp_path / "etc-dhcp" / "dhcpd.conf",
    )
    assert settings.staging_dir == tmp_path / "etc-dhcp"
    assert settings.staging_dir != settings.data_dir
