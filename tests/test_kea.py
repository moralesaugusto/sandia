import json
import shutil
import socketserver
import subprocess
import tempfile
import threading
from pathlib import Path

import pytest
from conftest import login, make_client

from sandia.config import JOURNAL, Settings
from sandia.dhcpd import apply as apply_module
from sandia.dhcpd import kea
from sandia.dhcpd.backend import (
    ISC,
    KEA,
    get_backend,
    load_current_leases,
    load_lease_records,
)
from sandia.dhcpd.parser import ParseError
from sandia.diagnostics import dhcp_log, diagnose_server
from sandia.diagnostics.kea_log import parse_kea_log
from sandia.diagnostics.models import Status
from sandia.leases import parse_lease_timestamp
from sandia.main import create_app
from sandia.utilization import subnet_utilization

FIXTURES = Path(__file__).parent / "fixtures"
KEA_CONF = FIXTURES / "sample_kea-dhcp4.conf"
KEA_LEASES = FIXTURES / "sample_kea-leases4.csv"
SUBNET_KEY = "192.0.2.0_255.255.255.0"

_BACKEND_ENV = ("SANDIA_DHCP_BACKEND", "DHCPD_CONF_PATH", "DHCPD_LEASES_PATH", "SANDIA_DHCP_LOG_PATH", "SANDIA_SERVICE_NAME")


@pytest.fixture
def clean_env(monkeypatch):
    for name in _BACKEND_ENV:
        monkeypatch.delenv(name, raising=False)


# Overrides conftest's `settings`, so the conftest app/client fixtures run
# against a Kea installation in this module.
@pytest.fixture
def settings(tmp_path) -> Settings:
    conf = tmp_path / "kea-dhcp4.conf"
    leases = tmp_path / "kea-leases4.csv"
    shutil.copyfile(KEA_CONF, conf)
    shutil.copyfile(KEA_LEASES, leases)
    return Settings(
        dhcp_backend="kea",
        data_dir=tmp_path / "data",
        dhcpd_conf_path=conf,
        leases_path=leases,
        backup_dir=tmp_path / "backups",
        interfaces_conf_path=tmp_path / "isc-dhcp-server-defaults",
        dhcp_log_path=tmp_path / "kea-dhcp4.log",
    )


# --- settings ---------------------------------------------------------------


def test_backend_defaults_to_kea(clean_env):
    settings = Settings()
    assert settings.dhcp_backend == "kea"
    assert get_backend(settings) is KEA
    assert settings.dhcpd_conf_path == Path("/etc/kea/kea-dhcp4.conf")
    assert settings.staging_path == Path("/etc/kea/.sandia-staged.conf")
    assert settings.leases_path == Path("/var/lib/kea/kea-leases4.csv")
    assert settings.dhcp_log_path == JOURNAL
    assert settings.service_name == "kea-dhcp4-server"
    assert settings.kea_control_socket == Path("/run/kea/kea4-ctrl-socket")


def test_legacy_isc_backend_keeps_its_defaults(clean_env, monkeypatch):
    monkeypatch.setenv("SANDIA_DHCP_BACKEND", "isc")
    settings = Settings()
    assert get_backend(settings) is ISC
    assert settings.dhcpd_conf_path == Path("/etc/dhcp/dhcpd.conf")
    assert settings.leases_path == Path("/var/lib/dhcp/dhcpd.leases")
    assert settings.dhcp_log_path == Path("/var/log/syslog")
    assert settings.service_name == "isc-dhcp-server"
    assert settings.interfaces_conf_path == Path("/etc/default/isc-dhcp-server")


def test_explicit_env_vars_win_over_backend_defaults(clean_env, monkeypatch):
    monkeypatch.setenv("SANDIA_DHCP_BACKEND", "kea")
    monkeypatch.setenv("DHCPD_CONF_PATH", "/srv/kea.conf")
    monkeypatch.setenv("SANDIA_SERVICE_NAME", "isc-kea-dhcp4-server")
    settings = Settings()
    assert settings.dhcpd_conf_path == Path("/srv/kea.conf")
    assert settings.service_name == "isc-kea-dhcp4-server"


def test_invalid_backend_fails_at_startup(clean_env, monkeypatch):
    monkeypatch.setenv("SANDIA_DHCP_BACKEND", "dnsmasq")
    with pytest.raises(ValueError, match="SANDIA_DHCP_BACKEND"):
        Settings()


def test_kea_dummy_mode_is_sandboxed(clean_env, tmp_path):
    settings = Settings(dhcp_backend="kea", dummy_data=True, data_dir=tmp_path)
    for path in (settings.dhcpd_conf_path, settings.leases_path, settings.dhcp_log_path, settings.backup_dir):
        assert path.is_relative_to(tmp_path / "dummy")
    assert settings.dhcpd_conf_path.name == "kea-dhcp4.conf"


# --- config projection --------------------------------------------------------


def test_projection_maps_subnets_pools_options_and_reservations():
    config = kea.parse_kea_config(KEA_CONF.read_text())

    assert [subnet.key for subnet in config.subnets] == [SUBNET_KEY, "198.51.100.0_255.255.255.0"]
    main, lab = config.subnets
    assert main.get("range") == "192.0.2.100 192.0.2.199"
    assert main.get("routers") == "192.0.2.1"
    assert lab.get("range") == "198.51.100.0 198.51.100.15"  # CIDR pool

    printer, by_client_id = main.hosts
    assert (printer.name, printer.mac, printer.fixed_address) == ("printer", "b8:27:eb:12:34:56", "192.0.2.50")
    assert by_client_id.mac is None  # not a hw-address reservation; no MAC is invented
    assert [(h.name, h.mac) for h in config.top_level_hosts] == [("global-host", "aa:bb:cc:00:00:01")]
    assert config.get("domain-name-servers") == "192.0.2.53"


def test_plain_json_keeps_comment_markers_inside_strings():
    assert kea.to_plain_json('{"url": "http://x/#a", "b": [1,]} // c') == '{"url": "http://x/#a", "b": [1]} '


def test_projection_resolves_includes(tmp_path):
    (tmp_path / "subnets.json").write_text('// included\n{ "subnet": "10.1.0.0/24", "pools": [ { "pool": "10.1.0.10 - 10.1.0.20" } ], },')
    config = kea.parse_kea_config(f'{{"Dhcp4": {{"subnet4": [ <?include "{tmp_path}/subnets.json"?> ]}}}}')
    assert [subnet.key for subnet in config.subnets] == ["10.1.0.0_255.255.255.0"]


def test_projection_reports_missing_include_and_bad_json_clearly(tmp_path):
    with pytest.raises(ParseError, match="cannot read included file"):
        kea.parse_kea_config(f'{{"Dhcp4": <?include "{tmp_path}/missing.json"?>}}')
    with pytest.raises(ParseError, match="invalid Kea JSON"):
        kea.parse_kea_config('{"Dhcp4": {')


def test_structured_writes_refuse_includes(tmp_path):
    (tmp_path / "x.json").write_text('{ "subnet": "10.1.0.0/24" }')
    text = f'{{"Dhcp4": {{"option-data": [], "subnet4": [ <?include "{tmp_path}/x.json"?> ]}}}}'
    with pytest.raises(ParseError, match="Raw Config"):
        kea.render_kea_config(text, kea.parse_kea_config(text))


def test_configured_interfaces():
    assert kea.configured_interfaces(KEA_CONF.read_text()) == ["eth0"]


# --- leases ------------------------------------------------------------------


def test_leases_last_row_wins_and_deletions_drop_out():
    leases = {lease.ip: lease for lease in kea.parse_kea_leases(KEA_LEASES.read_text())}

    assert set(leases) == {"192.0.2.100", "192.0.2.102", "192.0.2.103", "192.0.2.104"}  # .101 was deleted
    laptop = leases["192.0.2.100"]
    assert (laptop.mac, laptop.hostname, laptop.binding_state) == ("ac:de:48:22:33:44", "laptop, renamed", "active")
    assert parse_lease_timestamp(laptop.starts).isoformat() == "2026-09-02T12:00:00"
    assert parse_lease_timestamp(laptop.ends).isoformat() == "2026-09-02T13:00:00"
    assert [leases[ip].binding_state for ip in ("192.0.2.102", "192.0.2.103", "192.0.2.104")] == ["abandoned", "free", "released"]


def test_lease_history_keeps_every_record_but_not_deletions():
    history = kea.parse_kea_lease_history(KEA_LEASES.read_text())
    assert [r.ip for r in history].count("192.0.2.100") == 2
    assert [r.ip for r in history].count("192.0.2.101") == 1


def test_lease_loading_merges_lfc_output_first(settings):
    header = KEA_LEASES.read_text().splitlines()[0]
    lfc = settings.leases_path.with_name(settings.leases_path.name + ".2")
    lfc.write_text(f"{header}\n192.0.2.150,11:22:33:44:55:66,,3600,1788350400,1,0,0,old,0,,0\n")

    ips = {lease.ip for lease in load_current_leases(settings)}

    assert "192.0.2.150" in ips and "192.0.2.100" in ips
    assert len(load_lease_records(settings)) == 7


# --- log ---------------------------------------------------------------------


def test_log_file_format_normalizes_to_dhcp_events():
    lines = (
        "2026-09-02 09:15:00.212 INFO  [kea-dhcp4.leases/812.140] DHCP4_LEASE_ALLOC [hwtype=1 AC:DE:48:22:33:44], cid=[no info], tid=0x1a2b: lease 192.0.2.100 has been allocated for 3600 seconds\n"
        "2026-09-02 09:16:00.000 INFO  [kea-dhcp4.leases/812.140] DHCP4_LEASE_OFFER [hwtype=1 ac:de:48:22:33:44], cid=[no info], tid=0x1: lease 192.0.2.100 will be offered\n"
        "2026-09-02 09:17:00.000 INFO  [kea-dhcp4.leases/812.140] DHCP4_RELEASE [hwtype=1 ac:de:48:22:33:44], cid=[no info], tid=0x2: address 192.0.2.100 was released properly.\n"
        "2026-09-02 09:18:00.000 INFO  [kea-dhcp4.leases/812.140] DHCP4_DECLINE_LEASE Received DHCPDECLINE for addr 192.0.2.102 from client [hwtype=1 de:ad:be:ef:00:01], cid=[no info], tid=0x3. The lease will be unavailable for 86400 seconds.\n"
        "2026-09-02 09:19:00.000 DEBUG [kea-dhcp4.bad-packets/812.140] DHCP4_PACKET_NAK_0004 [hwtype=1 aa:bb:cc:00:11:22], cid=[no info], tid=0x4: failed to grant a lease, client sent ciaddr 0.0.0.0, requested-ip-address 192.0.2.220\n"
        "2026-09-02 09:20:00.000 DEBUG [kea-dhcp4.bad-packets/812.140] DHCP4_PACKET_NAK_0003 [hwtype=1 aa:bb:cc:00:11:23], cid=[no info], tid=0x5: failed to advertise a lease, client sent ciaddr 0.0.0.0, requested-ip-address (no address)\n"
        "2026-09-02 09:21:00.000 WARN  [kea-dhcp4.alloc-engine/812.140] ALLOC_ENGINE_V4_ALLOC_FAIL [hwtype=1 aa:bb:cc:00:11:24], cid=[no info], tid=0x6: failed to allocate an IPv4 address after 100 attempt(s)\n"
        "2026-09-02 09:22:00.000 INFO  [unrelated.logger/1.1] SOMETHING_ELSE not ours\n"
    )

    events = parse_kea_log(lines)

    assert [(e.kind, e.ip, e.mac) for e in events] == [
        ("DHCPACK", "192.0.2.100", "ac:de:48:22:33:44"),
        ("DHCPOFFER", "192.0.2.100", "ac:de:48:22:33:44"),
        ("DHCPRELEASE", "192.0.2.100", "ac:de:48:22:33:44"),
        ("DHCPDECLINE", "192.0.2.102", "de:ad:be:ef:00:01"),
        ("DHCPNAK", "192.0.2.220", "aa:bb:cc:00:11:22"),
        ("DHCPDISCOVER", None, "aa:bb:cc:00:11:23"),
        ("OTHER", None, None),
    ]
    assert events[0].timestamp == "Sep  2 09:15:00"
    assert events[4].reason == "failed to grant a lease"
    assert events[0].hostname is None and events[0].iface is None  # Kea doesn't log these; not guessed


def test_log_syslog_forms():
    events = parse_kea_log(
        "Sep  2 09:15:00 host kea-dhcp4[812]: INFO  [kea-dhcp4.leases.140] DHCP4_LEASE_ALLOC [hwtype=1 ac:de:48:22:33:44], cid=[no info], tid=0x1: lease 192.0.2.100 has been allocated for 3600 seconds\n"
        "Sep  2 09:16:00 host kea-dhcp4[812]: INFO  DHCP4_LEASE_OFFER [hwtype=1 ac:de:48:22:33:44], cid=[no info], tid=0x2: lease 192.0.2.100 will be offered\n"
        "Sep  2 09:17:00 host dhcpd[1]: DHCPACK on 192.0.2.9 to aa:bb:cc:dd:ee:ff via eth0\n"
    )
    assert [(e.timestamp, e.kind) for e in events] == [("Sep  2 09:15:00", "DHCPACK"), ("Sep  2 09:16:00", "DHCPOFFER")]


# --- apply / service -----------------------------------------------------------


def _fake_run(calls, failing=()):
    async def fake_run(*args):
        calls.append(args)
        if args[0] in failing:
            return apply_module.CommandResult(ok=False, stdout="", stderr=f"{args[0]} failed")
        return apply_module.CommandResult(ok=True, stdout="active", stderr="")

    return fake_run


async def test_kea_apply_validates_installs_and_restarts(settings, monkeypatch):
    calls = []
    monkeypatch.setattr(apply_module, "_run", _fake_run(calls))
    new_text = KEA_CONF.read_text().replace('"eth0"', '"eth1"')

    result = await apply_module.apply_new_config(settings, new_text)

    assert result.ok, result.output
    assert settings.dhcpd_conf_path.read_text() == new_text
    assert calls == [
        ("kea-dhcp4", "-t", str(settings.staging_path)),
        ("systemctl", "restart", settings.service_name),
        ("systemctl", "is-active", settings.service_name),
    ]
    assert [p.name.split(".2")[0] for p in settings.backup_dir.iterdir()] == ["kea-dhcp4.conf"]


async def test_kea_apply_stops_on_rejected_config(settings, monkeypatch):
    calls = []
    monkeypatch.setattr(apply_module, "_run", _fake_run(calls, failing=("kea-dhcp4",)))

    result = await apply_module.apply_new_config(settings, "{}")

    assert (result.ok, result.stage) == (False, "check")
    assert settings.dhcpd_conf_path.read_text() == KEA_CONF.read_text()


async def test_kea_apply_rolls_back_when_service_fails(settings, monkeypatch):
    statuses = iter(["failed", "active"])

    async def fake_run(*args):
        if args[:2] == ("systemctl", "is-active"):
            return apply_module.CommandResult(ok=True, stdout=next(statuses), stderr="")
        return apply_module.CommandResult(ok=True, stdout="", stderr="")

    monkeypatch.setattr(apply_module, "_run", fake_run)

    result = await apply_module.apply_new_config(settings, '{"Dhcp4": {}}')

    assert (result.ok, result.stage) == (False, "restart")
    assert "Rolled back" in result.output and "running again" in result.output
    assert settings.dhcpd_conf_path.read_text() == KEA_CONF.read_text()


async def test_kea_validator_missing_is_reported_as_unknown_not_invalid(settings, monkeypatch):
    async def fake_run(*args):
        if args[0] == "kea-dhcp4":
            return apply_module.CommandResult(ok=False, stdout="", stderr="No such file: kea-dhcp4", command_missing=True)
        return apply_module.CommandResult(ok=True, stdout="active", stderr="")

    monkeypatch.setattr(apply_module, "_run", fake_run)

    result = await diagnose_server(settings)

    finding = next(f for f in result.findings if "validate" in f.problem)
    assert finding.status == Status.WARNING
    assert "kea-dhcp4" in finding.root_cause
    assert all("isc-dhcp-server" not in f.problem and "INTERFACESv4" not in f.root_cause for f in result.findings)


async def test_kea_server_diagnostics_check_kea_interfaces(settings, monkeypatch):
    calls = []
    monkeypatch.setattr(apply_module, "_run", _fake_run(calls))
    settings.dhcpd_conf_path.write_text('{"Dhcp4": {"interfaces-config": {"interfaces": []}}}')

    result = await diagnose_server(settings)

    assert any("interfaces-config" in f.root_cause for f in result.findings)
    assert ("kea-dhcp4", "-t", str(settings.dhcpd_conf_path)) in calls


async def test_kea_service_control_uses_kea_unit(clean_env, monkeypatch):
    calls = []
    monkeypatch.setattr(apply_module, "_run", _fake_run(calls))
    settings = Settings(dhcp_backend="kea")

    await apply_module.restart_service(settings)
    await apply_module.enable_service(settings)
    await apply_module.disable_service(settings)
    assert await apply_module.service_status(settings) == "active"

    assert calls == [
        ("systemctl", "restart", "kea-dhcp4-server"),
        ("systemctl", "enable", "kea-dhcp4-server"),
        ("systemctl", "disable", "kea-dhcp4-server"),
        ("systemctl", "is-active", "kea-dhcp4-server"),
    ]


# --- routes in Kea mode ------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    ["/", "/subnets", f"/subnets/{SUBNET_KEY}/map", f"/subnets/{SUBNET_KEY}/map/192.0.2.100/menu", "/reservations",
     "/leases", "/devices", "/diagnostics/events", "/diagnostics/server", "/interfaces", "/backups", "/about"],
)
def test_read_views_render(admin_client, path):
    response = admin_client.get(path)
    assert response.status_code == 200, response.text
    assert "Kea DHCPv4" in response.text or path.endswith("/menu")


def _kea_config(settings) -> dict:
    return json.loads(kea.to_plain_json(settings.dhcpd_conf_path.read_text()))["Dhcp4"]


def _subnet_entry(settings, cidr: str) -> dict:
    return next(entry for entry in _kea_config(settings)["subnet4"] if entry["subnet"] == cidr)


def _flash_after(client, response) -> str:
    assert response.status_code == 303, response.text
    return client.get(response.headers["location"]).text


@pytest.fixture
def kea_socket(settings):
    """A stand-in kea-dhcp4 control socket. Records each command; answers
    from `responses[command]` (a dict, or a list consumed in order),
    defaulting to success."""
    directory = tempfile.mkdtemp(prefix="kea")  # AF_UNIX paths must stay short
    path = Path(directory) / "ctrl"
    received: list[dict] = []
    responses: dict = {}

    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            data = b""
            while chunk := self.request.recv(65536):
                data += chunk
                try:
                    request = json.loads(data)
                    break
                except ValueError:
                    continue
            received.append(request)
            answer = responses.get(request["command"], {"result": 0, "text": "ok"})
            if isinstance(answer, list):
                answer = answer.pop(0)
            self.request.sendall(json.dumps(answer).encode())

    server = socketserver.ThreadingUnixStreamServer(str(path), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    settings.kea_control_socket = path
    yield received, responses
    server.shutdown()
    server.server_close()
    shutil.rmtree(directory)


def test_map_menu_offers_write_actions(admin_client):
    menu = admin_client.get(f"/subnets/{SUBNET_KEY}/map/192.0.2.100/menu").text
    assert "Open device" in menu and "Reserve this lease" in menu and "/deny" in menu


def test_subnet_lifecycle_writes_kea_json_and_keeps_comments(admin_client, settings):
    page = _flash_after(
        admin_client,
        admin_client.post(
            "/subnets/new",
            data={
                "network": "10.20.0.0", "netmask": "255.255.255.0", "range_start": "10.20.0.100", "range_end": "10.20.0.200",
                "routers": "10.20.0.1", "interface": "eth1", "default_lease_time": "1200",
            },
        ),
    )
    assert "Subnet created. Configuration applied." in page
    text = settings.dhcpd_conf_path.read_text()
    assert "// Sample kea-dhcp4.conf for tests" in text and "/* Subnet reservations." in text
    entry = _subnet_entry(settings, "10.20.0.0/24")
    assert entry["id"] == 3
    assert entry["pools"] == [{"pool": "10.20.0.100 - 10.20.0.200"}]
    assert entry["option-data"] == [{"name": "routers", "data": "10.20.0.1"}]
    assert (entry["interface"], entry["valid-lifetime"]) == ("eth1", 1200)

    key = "10.20.0.0_255.255.255.0"
    assert admin_client.get(f"/subnets/{key}/edit").status_code == 200
    admin_client.post(f"/subnets/{key}/edit", data={"range_start": "10.20.0.50", "range_end": "10.20.0.60", "interface": ""})
    entry = _subnet_entry(settings, "10.20.0.0/24")
    assert entry["pools"] == [{"pool": "10.20.0.50 - 10.20.0.60"}]
    assert "interface" not in entry and "valid-lifetime" not in entry and "option-data" in entry

    admin_client.post(f"/subnets/{key}/delete")
    assert all(entry["subnet"] != "10.20.0.0/24" for entry in _kea_config(settings)["subnet4"])


def test_editing_a_subnet_keeps_unmanaged_keys_and_pools(admin_client, settings):
    text = settings.dhcpd_conf_path.read_text().replace('"id": 1,', '"id": 1, "relay": { "ip-addresses": [ "192.0.2.254" ] },')
    text = text.replace('[ { "pool": "192.0.2.100 - 192.0.2.199" } ]', '[ { "pool": "192.0.2.100 - 192.0.2.199" }, { "pool": "192.0.2.210 - 192.0.2.219", "client-class": "lab" } ]')
    settings.dhcpd_conf_path.write_text(text)

    admin_client.post(f"/subnets/{SUBNET_KEY}/edit", data={"range_start": "192.0.2.100", "range_end": "192.0.2.199", "routers": "192.0.2.254"})

    entry = _subnet_entry(settings, "192.0.2.0/24")
    assert entry["relay"] == {"ip-addresses": ["192.0.2.254"]}
    assert {"pool": "192.0.2.210 - 192.0.2.219", "client-class": "lab"} in entry["pools"]
    assert entry["option-data"] == [{"name": "routers", "data": "192.0.2.254"}]


def test_extra_options_become_option_data_and_other_statements_are_refused(admin_client, settings):
    admin_client.post(
        f"/subnets/{SUBNET_KEY}/edit",
        data={"range_start": "192.0.2.100", "range_end": "192.0.2.199", "routers": "192.0.2.1", "extra_options": "option domain-search example.com;"},
    )
    assert {"name": "domain-search", "data": "example.com"} in _subnet_entry(settings, "192.0.2.0/24")["option-data"]

    before = settings.dhcpd_conf_path.read_text()
    page = _flash_after(
        admin_client,
        admin_client.post(f"/subnets/{SUBNET_KEY}/edit", data={"range_start": "192.0.2.100", "range_end": "192.0.2.199", "extra_options": "allow unknown-clients;"}),
    )
    assert "Raw Config" in page
    assert settings.dhcpd_conf_path.read_text() == before


def test_reservation_lifecycle(admin_client, settings):
    page = _flash_after(
        admin_client,
        admin_client.post(
            "/reservations/new",
            data={"name": "laptop", "mac": "ac:de:48:22:33:44", "fixed_address": "192.0.2.60", "subnet_key": SUBNET_KEY, "client_hostname": "laptop-host"},
        ),
    )
    assert "Reservation created. Configuration applied." in page
    laptop = next(r for r in _subnet_entry(settings, "192.0.2.0/24")["reservations"] if r.get("hostname") == "laptop")
    assert (laptop["hw-address"], laptop["ip-address"]) == ("ac:de:48:22:33:44", "192.0.2.60")
    assert laptop["option-data"] == [{"name": "host-name", "data": "laptop-host"}]

    admin_client.post("/reservations/printer/edit", data={"mac": "b8:27:eb:12:34:56", "fixed_address": "192.0.2.52", "next_server": "192.0.2.5", "boot_filename": "pxelinux.0"})
    printer = next(r for r in _subnet_entry(settings, "192.0.2.0/24")["reservations"] if r.get("hostname") == "printer")
    assert printer["ip-address"] == "192.0.2.52"
    assert (printer["next-server"], printer["boot-file-name"]) == ("192.0.2.5", "pxelinux.0")
    assert printer["user-context"] == {"url": "http://printer/"}  # not modeled, kept

    admin_client.post("/reservations/laptop/delete")
    admin_client.post("/reservations/bulk-delete", data={"names": ["printer", "global-host"]})
    config = _kea_config(settings)
    assert [r.get("client-id") for r in config["subnet4"][0]["reservations"]] == ["01:11:22:33:44:55:66"]
    assert config["reservations"] == []


def test_global_settings_map_to_kea_globals(admin_client, settings):
    assert admin_client.get("/settings").status_code == 200
    page = _flash_after(
        admin_client,
        admin_client.post(
            "/settings",
            data={"authoritative": "true", "default_lease_time": "900", "max_lease_time": "7200", "domain_name": "example.test", "domain_name_servers": "192.0.2.53, 192.0.2.54"},
        ),
    )
    assert "Global settings applied." in page
    config = _kea_config(settings)
    assert (config["authoritative"], config["valid-lifetime"], config["max-valid-lifetime"]) == (True, 900, 7200)
    assert {"name": "domain-name", "data": "example.test"} in config["option-data"]
    assert {"name": "domain-name-servers", "data": "192.0.2.53, 192.0.2.54"} in config["option-data"]

    admin_client.post("/settings", data={"default_lease_time": "900", "max_lease_time": "7200"})
    assert "authoritative" not in _kea_config(settings)


def test_deny_client_uses_the_drop_class(admin_client, settings):
    page = _flash_after(admin_client, admin_client.post("/leases/192.0.2.100/deny"))
    assert "Client denied. Configuration applied." in page
    assert _kea_config(settings)["client-classes"] == [{"name": "DROP", "test": "pkt4.mac == 0xacde48223344"}]
    assert "Client denied" in admin_client.get(f"/subnets/{SUBNET_KEY}/map/192.0.2.100/menu").text

    admin_client.post("/reservations/deny-acde48223344/delete")
    assert _kea_config(settings)["client-classes"] == []


def test_deny_rejects_a_mac_that_is_not_a_mac(admin_client, settings):
    admin_client.post("/leases/192.0.2.100/deny")
    before = settings.dhcpd_conf_path.read_text()
    page = _flash_after(admin_client, admin_client.post("/reservations/deny-acde48223344/edit", data={"mac": "aa or true", "fixed_address": "192.0.2.99"}))
    assert "is not a MAC address" in page
    assert settings.dhcpd_conf_path.read_text() == before


def test_hand_written_drop_class_is_left_alone(admin_client, settings):
    text = settings.dhcpd_conf_path.read_text().replace('"valid-lifetime": 3600,', '"valid-lifetime": 3600, "client-classes": [ { "name": "DROP", "test": "substring(option[60].hex,0,4) == \'evil\'" } ],')
    settings.dhcpd_conf_path.write_text(text)

    page = _flash_after(admin_client, admin_client.post("/leases/192.0.2.100/deny"))

    assert "hand-written DROP class" in page
    assert settings.dhcpd_conf_path.read_text() == text


def test_interfaces_editor_applies_kea_interfaces(admin_client, settings):
    assert "Dhcp4.interfaces-config.interfaces" in admin_client.get("/interfaces").text
    page = _flash_after(admin_client, admin_client.post("/interfaces", data={"interfaces": "eth0, eth1"}))
    assert "Interfaces updated. Configuration applied." in page
    assert _kea_config(settings)["interfaces-config"]["interfaces"] == ["eth0", "eth1"]
    assert "// Sample kea-dhcp4.conf for tests" in settings.dhcpd_conf_path.read_text()


def test_device_lease_page_suggests_a_free_address(admin_client):
    page = admin_client.get("/devices/de:ad:be:ef:00:01/lease")
    assert page.status_code == 200
    assert "192.0.2.101" in page.text  # first pool address without an active lease


def test_delete_lease_uses_lease4_del(admin_client, settings, kea_socket):
    received, _responses = kea_socket
    page = _flash_after(admin_client, admin_client.post("/devices/ac:de:48:22:33:44/delete-lease"))
    assert received == [{"command": "lease4-del", "arguments": {"ip-address": "192.0.2.100"}}]
    assert "Kea deleted the lease for 192.0.2.100" in page
    assert settings.leases_path.read_text() == KEA_LEASES.read_text()  # Kea owns the file


def test_delete_lease_reports_kea_errors(admin_client, kea_socket):
    _received, responses = kea_socket
    responses["lease4-del"] = {"result": 2, "text": "'lease4-del' command not supported."}
    page = _flash_after(admin_client, admin_client.post("/devices/bulk-delete-lease", data={"macs": ["ac:de:48:22:33:44"]}))
    assert "command not supported" in page


def test_delete_lease_without_control_socket_says_so(admin_client, settings, tmp_path):
    settings.kea_control_socket = tmp_path / "missing"
    page = _flash_after(admin_client, admin_client.post("/devices/ac:de:48:22:33:44/delete-lease"))
    assert "cannot connect to the Kea control socket" in page


def test_lease_cleanup_is_left_to_kea(admin_client, settings):
    page = _flash_after(admin_client, admin_client.post("/leases/clean"))
    assert "Kea compacts its lease file itself" in page
    assert settings.leases_path.read_text() == KEA_LEASES.read_text()


async def test_apply_uses_config_reload_when_the_control_socket_exists(settings, kea_socket, monkeypatch):
    received, _responses = kea_socket
    calls = []
    monkeypatch.setattr(apply_module, "_run", _fake_run(calls))

    result = await apply_module.apply_new_config(settings, KEA_CONF.read_text())

    assert result.ok and "reloaded its configuration" in result.output
    assert received == [{"command": "config-reload"}]
    assert ("systemctl", "restart", settings.service_name) not in calls


async def test_rejected_config_reload_rolls_back(settings, kea_socket, monkeypatch):
    _received, responses = kea_socket
    responses["config-reload"] = [{"result": 1, "text": "subnet id 7 is already in use"}, {"result": 0, "text": "ok"}]
    monkeypatch.setattr(apply_module, "_run", _fake_run([]))

    result = await apply_module.apply_new_config(settings, '{"Dhcp4": {}}')

    assert (result.ok, result.stage) == (False, "restart")
    assert "subnet id 7 is already in use" in result.output and "running again" in result.output
    assert settings.dhcpd_conf_path.read_text() == KEA_CONF.read_text()


def test_multiple_pools_fill_the_map_and_utilization(admin_client, settings):
    text = settings.dhcpd_conf_path.read_text().replace('[ { "pool": "192.0.2.100 - 192.0.2.199" } ]', '[ { "pool": "192.0.2.100 - 192.0.2.109" }, { "pool": "192.0.2.150 - 192.0.2.159" } ]')
    settings.dhcpd_conf_path.write_text(text)
    subnet = kea.parse_kea_config(text).find_subnet(SUBNET_KEY)

    assert subnet_utilization(subnet, load_current_leases(settings)) == (1, 20)  # only .100 is active
    page = admin_client.get(f"/subnets/{SUBNET_KEY}/map").text
    assert "192.0.2.155" in page and "192.0.2.120" not in page


def test_journal_is_the_default_kea_log_source(settings, monkeypatch):
    settings.dhcp_log_path = JOURNAL
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="Sep 02 09:15:00 host kea-dhcp4[812]: INFO  DHCP4_LEASE_ALLOC [hwtype=1 ac:de:48:22:33:44], cid=[no info], tid=0x1: lease 192.0.2.100 has been allocated for 3600 seconds\n", stderr="")

    monkeypatch.setattr(dhcp_log.subprocess, "run", fake_run)
    events, unavailable = dhcp_log.load_dhcp_events(settings)

    assert unavailable is None
    assert [(e.kind, e.ip) for e in events] == [("DHCPACK", "192.0.2.100")]
    assert calls[0][:3] == ["journalctl", "--unit", settings.service_name]
    assert dhcp_log.log_source_label(settings) == f"systemd journal ({settings.service_name})"


def test_journal_failure_is_reported(settings, monkeypatch):
    settings.dhcp_log_path = JOURNAL
    monkeypatch.setattr(dhcp_log.subprocess, "run", lambda args, **kw: subprocess.CompletedProcess(args, 1, stdout="", stderr="No journal files were found."))
    assert dhcp_log.load_dhcp_events(settings) == ([], "journalctl failed: No journal files were found.")


def test_client_diagnostics_explain_kea_logging(admin_client, settings):
    settings.dhcp_log_path.write_text("")
    page = admin_client.get("/diagnostics/client?mac=11:22:33:44:55:66").text
    assert "DISCOVER, REQUEST and NAK appear only with debug logging" in page


def test_raw_config_shows_file_verbatim_and_applies(admin_client, settings):
    page = admin_client.get("/config/raw").text
    assert "// Sample kea-dhcp4.conf for tests" in page

    new_text = KEA_CONF.read_text().replace('"eth0"', '"eth1"')
    diff = admin_client.post("/config/raw/diff", data={"text": new_text}).text
    assert "kea-dhcp4.conf" in diff and "eth1" in diff
    assert "test double" not in admin_client.post("/config/raw/validate", data={"text": new_text}).text

    response = admin_client.post("/config/raw/apply", data={"text": new_text})

    assert response.status_code == 303
    assert settings.dhcpd_conf_path.read_text() == new_text
    assert "Kea DHCPv4 restarted" in admin_client.get("/config/raw").text


def test_raw_config_rejects_invalid_kea_json(admin_client, settings):
    response = admin_client.post("/config/raw/apply", data={"text": '{"Dhcp4": {'})
    assert response.status_code == 303
    assert settings.dhcpd_conf_path.read_text() == KEA_CONF.read_text()


def test_kea_dummy_mode_never_runs_commands(clean_env, tmp_path, monkeypatch):
    async def no_commands(*args):
        raise AssertionError(f"dummy mode ran {args}")

    monkeypatch.setattr(apply_module, "_run", no_commands)
    settings = Settings(dhcp_backend="kea", dummy_data=True, data_dir=tmp_path, enable_https=False)
    client = make_client(create_app(settings))
    login(client, "admin", "admin")

    assert "johns-laptop" in client.get("/leases").text
    assert client.get("/subnets/192.168.50.0_255.255.255.0/map").status_code == 200
    assert client.get("/diagnostics/server").status_code == 200
    assert client.post("/service/restart").status_code == 303
