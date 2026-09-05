import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from sandia.config import Settings
from sandia.main import create_app
from sandia.models import User
from sandia.security import hash_password

FIXTURE_CONF = Path(__file__).parent / "fixtures" / "sample_dhcpd.conf"
FIXTURE_LEASES = Path(__file__).parent / "fixtures" / "sample_dhcpd.leases"

ADMIN_PASSWORD = "admin-pass-123"
OPERATOR_PASSWORD = "operator-pass-123"
VIEWER_PASSWORD = "viewer-pass-123"


@pytest.fixture
def settings(tmp_path) -> Settings:
    data_dir = tmp_path / "data"
    dhcpd_conf = tmp_path / "dhcpd.conf"
    leases = tmp_path / "dhcpd.leases"
    backup_dir = tmp_path / "backups"
    shutil.copyfile(FIXTURE_CONF, dhcpd_conf)
    shutil.copyfile(FIXTURE_LEASES, leases)
    return Settings(
        data_dir=data_dir,
        dhcpd_conf_path=dhcpd_conf,
        leases_path=leases,
        backup_dir=backup_dir,
    )


@pytest.fixture
def app(settings, monkeypatch):
    # Real installs are now plain file I/O against `settings`' own tmp_path
    # locations, so no faking is needed there. Only the external binaries
    # (`dhcpd -t`, `systemctl`) need a double, since they may not exist (or
    # may not reflect test state) in the test environment.
    from sandia.dhcpd import apply as apply_module

    async def fake_run(*args):
        if args[:1] == ("dhcpd",):
            text = Path(args[-1]).read_text()
            if text.count("{") != text.count("}") or "FORCE_INVALID" in text:
                return apply_module.CommandResult(ok=False, stdout="", stderr="invalid config (test double)")
            return apply_module.CommandResult(ok=True, stdout="", stderr="")
        if args[:1] == ("systemctl",):
            return apply_module.CommandResult(ok=True, stdout="active", stderr="")
        raise AssertionError(f"unexpected command in tests: {args}")

    monkeypatch.setattr(apply_module, "_run", fake_run)

    application = create_app(settings)
    with Session(application.state.engine) as session:
        for username, password, role in [
            ("admin", ADMIN_PASSWORD, "admin"),
            ("operator", OPERATOR_PASSWORD, "operator"),
            ("viewer", VIEWER_PASSWORD, "viewer"),
        ]:
            existing = session.exec(select(User).where(User.username == username)).first()
            if existing is None:
                session.add(User(username=username, password_hash=hash_password(password), role=role))
            else:
                # The app's own startup bootstrap may have already created
                # "admin" with a random password; pin it to the known one.
                existing.password_hash = hash_password(password)
                existing.role = role
                session.add(existing)
        session.commit()
    return application


@pytest.fixture
def client(app):
    return TestClient(app, base_url="http://testserver", follow_redirects=False)


def login(client: TestClient, username: str, password: str) -> None:
    response = client.post("/login", data={"username": username, "password": password})
    assert response.status_code == 303, response.text


@pytest.fixture
def admin_client(client):
    login(client, "admin", ADMIN_PASSWORD)
    return client


@pytest.fixture
def operator_client(client):
    login(client, "operator", OPERATOR_PASSWORD)
    return client


@pytest.fixture
def viewer_client(client):
    login(client, "viewer", VIEWER_PASSWORD)
    return client
