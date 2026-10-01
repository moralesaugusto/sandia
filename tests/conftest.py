import json
import re
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from sandia.config import Settings
from sandia.dhcpd.kea import to_plain_json
from sandia.main import create_app
from sandia.models import User
from sandia.security import hash_password

FIXTURE_CONF = Path(__file__).parent / "fixtures" / "sample_dhcpd.conf"
FIXTURE_LEASES = Path(__file__).parent / "fixtures" / "sample_dhcpd.leases"

ADMIN_PASSWORD = "admin-pass-123"
OPERATOR_PASSWORD = "operator-pass-123"
VIEWER_PASSWORD = "viewer-pass-123"


@pytest.fixture(autouse=True)
def _legacy_isc_backend_by_default(monkeypatch):
    # Kea is the default backend; the pre-Kea test suite exercises the ISC
    # backend, so it keeps running against ISC unless a test opts into Kea.
    monkeypatch.setenv("SANDIA_DHCP_BACKEND", "isc")


@pytest.fixture
def settings(tmp_path) -> Settings:
    data_dir = tmp_path / "data"
    dhcpd_conf = tmp_path / "dhcpd.conf"
    leases = tmp_path / "dhcpd.leases"
    backup_dir = tmp_path / "backups"
    interfaces_conf = tmp_path / "isc-dhcp-server-defaults"
    shutil.copyfile(FIXTURE_CONF, dhcpd_conf)
    shutil.copyfile(FIXTURE_LEASES, leases)
    return Settings(
        data_dir=data_dir,
        dhcpd_conf_path=dhcpd_conf,
        leases_path=leases,
        backup_dir=backup_dir,
        interfaces_conf_path=interfaces_conf,
        # Explicit and non-existent by default (rather than falling through
        # to the real default of /var/log/syslog) so tests are deterministic
        # regardless of what's on the machine running them.
        dhcp_log_path=tmp_path / "dhcpd.log",
    )


@pytest.fixture
def app(settings, monkeypatch):
    # Real installs are now plain file I/O against `settings`' own tmp_path
    # locations, so no faking is needed there. Only the external binaries
    # (`dhcpd -t`, `kea-dhcp4 -t`, `systemctl`) need a double, since they may
    # not exist (or may not reflect test state) in the test environment.
    from sandia.dhcpd import apply as apply_module

    async def fake_run(*args):
        if args[:1] == ("dhcpd",):
            text = Path(args[-1]).read_text()
            if text.count("{") != text.count("}") or "FORCE_INVALID" in text:
                return apply_module.CommandResult(ok=False, stdout="", stderr="invalid config (test double)")
            return apply_module.CommandResult(ok=True, stdout="", stderr="")
        if args[:1] == ("kea-dhcp4",):
            try:
                json.loads(to_plain_json(Path(args[-1]).read_text()))
            except ValueError:
                return apply_module.CommandResult(ok=False, stdout="", stderr="invalid Kea config (test double)")
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


def fetch_csrf_token(client: TestClient) -> str:
    """Read the session's CSRF token from a rendered page and send it on every later request."""
    response = client.get("/login")
    if response.status_code == 303:  # already logged in
        response = client.get("/account/password")
    token = re.search(r'name="csrf_token" value="([^"]+)"', response.text).group(1)
    client.headers["X-CSRF-Token"] = token
    return token


def make_client(app, base_url: str = "https://testserver") -> TestClient:
    client = TestClient(app, base_url=base_url, follow_redirects=False)
    fetch_csrf_token(client)
    return client


@pytest.fixture
def client(app):
    return make_client(app)


def login(client: TestClient, username: str, password: str) -> None:
    fetch_csrf_token(client)  # the session may be new or cleared by a logout
    response = client.post("/login", data={"username": username, "password": password})
    assert response.status_code == 303, response.text
    # Logging in rotates the token.
    fetch_csrf_token(client)


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
