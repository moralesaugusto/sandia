from conftest import login, make_client, submit
from sqlmodel import Session, select

from sandia.config import Settings
from sandia.main import create_app
from sandia.models import User
from sandia.security import hash_password


def test_dummy_data_never_targets_real_system_paths(tmp_path):
    settings = Settings(
        data_dir=tmp_path / "data",
        dhcpd_conf_path=tmp_path / "should-be-ignored" / "dhcpd.conf",
        leases_path=tmp_path / "should-be-ignored" / "dhcpd.leases",
        dummy_data=True,
    )
    assert settings.dhcpd_conf_path == tmp_path / "data" / "dummy" / "dhcpd.conf"
    assert settings.leases_path == tmp_path / "data" / "dummy" / "dhcpd.leases"
    assert settings.backup_dir == tmp_path / "data" / "dummy" / "backups"
    assert not (tmp_path / "should-be-ignored").exists()


def test_dummy_data_seeds_files_once(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", dummy_data=True)
    create_app(settings)

    assert settings.dhcpd_conf_path.exists()
    assert settings.leases_path.exists()
    assert "192.168.50.0" in settings.dhcpd_conf_path.read_text()

    # A prior "session" edit should survive a second app start.
    settings.dhcpd_conf_path.write_text("authoritative;\n")
    create_app(settings)
    assert settings.dhcpd_conf_path.read_text() == "authoritative;\n"


def test_non_dummy_mode_bootstraps_random_admin_password(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", dummy_data=False)
    app = create_app(settings)

    password_file = settings.initial_password_path
    assert password_file.stat().st_mode & 0o777 == 0o600
    password = password_file.read_text().strip()
    assert password != "admin"

    client = make_client(app)
    assert client.post("/login", data={"username": "admin", "password": "admin"}).status_code != 303
    assert client.post("/login", data={"username": "admin", "password": password}).status_code == 303


def test_dummy_mode_bootstraps_fixed_admin_credentials(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", dummy_data=True)
    app = create_app(settings)

    with Session(app.state.engine) as session:
        admin = session.exec(select(User)).first()
        assert admin.username == "admin"

    client = make_client(app)
    login(client, "admin", "admin")


def test_dummy_mode_without_explicit_data_dir_does_not_need_root(monkeypatch, tmp_path):
    # Regression test: constructing Settings(dummy_data=True) directly
    # (not via the CLI/env-var path) must not fall back to /var/lib/sandia.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("SANDIA_DATA_DIR", raising=False)

    settings = Settings(dummy_data=True)
    create_app(settings)  # must not raise PermissionError

    assert settings.data_dir == tmp_path / ".local" / "share" / "sandia-dummy"


def test_dummy_mode_full_ui_flow_without_sudo_or_real_dhcpd(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", dummy_data=True)
    app = create_app(settings)

    with Session(app.state.engine) as session:
        admin = session.exec(select(User)).first()
        admin.password_hash = hash_password("testpass123")
        session.add(admin)
        session.commit()

    client = make_client(app)
    login(client, "admin", "testpass123")

    dashboard = client.get("/")
    assert dashboard.status_code == 200
    assert b"192.168.50.0" in dashboard.content

    leases = client.get("/leases")
    assert leases.status_code == 200
    assert b"192.168.50.50" in leases.content

    create = submit(
        client,
        "/subnets/new",
        data={
            "network": "172.20.0.0",
            "netmask": "255.255.255.0",
            "range_start": "172.20.0.10",
            "range_end": "172.20.0.50",
        },
    )
    assert create.status_code == 303
    assert "172.20.0.0" in settings.dhcpd_conf_path.read_text()

    restart = client.post("/service/restart")
    assert restart.status_code == 303

    status = client.get("/service")
    assert b"active" in status.content
