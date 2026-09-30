from datetime import datetime, timedelta

from sandia.devices import (
    RECENT_WINDOW,
    DeviceStatus,
    build_devices,
    filter_devices,
    find_device,
    sort_devices,
)
from sandia.dhcpd import parse
from sandia.diagnostics.dhcp_log import parse_dhcp_log
from sandia.leases import parse_lease_history, parse_leases

CONF = """
subnet 10.0.0.0 netmask 255.255.255.0 {
    range 10.0.0.10 10.0.0.50;
    host res_a {
        hardware ethernet aa:aa:aa:aa:aa:01;
        fixed-address 10.0.0.20;
    }
}
host deny-bbbbbbbbbb02 {
    hardware ethernet bb:bb:bb:bb:bb:02;
    deny booting;
}
"""


def _fmt(dt: datetime) -> str:
    return f"{dt.isoweekday() % 7} {dt.strftime('%Y/%m/%d %H:%M:%S')}"


def _block(ip: str, mac: str, state: str, start: datetime, end: datetime, hostname: str | None = None) -> str:
    hostname_line = f'  client-hostname "{hostname}";\n' if hostname else ""
    return f"lease {ip} {{\n  starts {_fmt(start)};\n  ends {_fmt(end)};\n  binding state {state};\n  hardware ethernet {mac};\n{hostname_line}}}\n"


def _build(now: datetime):
    conf = CONF
    leases_text = "".join(
        [
            # res_a: reserved, active, has an identifiable hostname from the lease itself.
            _block("10.0.0.20", "aa:aa:aa:aa:aa:01", "active", now - timedelta(hours=1), now + timedelta(hours=5), hostname="res-a-device"),
            # dynamic, unreserved, currently active - but flagged via a DHCPNAK below.
            _block("10.0.0.21", "cc:cc:cc:cc:cc:03", "active", now - timedelta(hours=2), now + timedelta(hours=4), hostname="dynamic-device"),
            # denied MAC with an active lease - a problem by definition.
            _block("10.0.0.23", "bb:bb:bb:bb:bb:02", "active", now - timedelta(hours=1), now + timedelta(hours=5)),
            # ee:...:05 held 10.0.0.30 in the past (now free) and holds 10.0.0.31 now (active) -
            # proves "multiple historical IPs for one MAC".
            _block("10.0.0.30", "ee:ee:ee:ee:ee:05", "free", now - timedelta(days=10), now - timedelta(days=9, hours=12)),
            _block("10.0.0.31", "ee:ee:ee:ee:ee:05", "active", now - timedelta(hours=3), now + timedelta(hours=3)),
            # gg:...:07 held 10.0.0.40 in the past; hh:...:08 holds it now - gg's block is
            # superseded out of "current" leases but survives in history only.
            _block("10.0.0.40", "gg:gg:gg:gg:gg:07", "expired", now - timedelta(days=20), now - timedelta(days=19, hours=12)),
            _block("10.0.0.40", "hh:hh:hh:hh:hh:08", "active", now - timedelta(hours=1), now + timedelta(hours=5)),
        ]
    )
    events_text = (
        "Sep  1 08:00:00 host dhcpd[1]: DHCPDISCOVER from aa:aa:aa:aa:aa:01 via eth0\n"
        "Sep  1 08:00:00 host dhcpd[1]: DHCPOFFER on 10.0.0.20 to aa:aa:aa:aa:aa:01 via eth0\n"
        "Sep  1 08:00:01 host dhcpd[1]: DHCPREQUEST for 10.0.0.20 from aa:aa:aa:aa:aa:01 via eth0\n"
        "Sep  1 08:00:01 host dhcpd[1]: DHCPACK on 10.0.0.20 to aa:aa:aa:aa:aa:01 via eth0\n"
        "Sep  2 09:05:00 host dhcpd[1]: DHCPNAK on 10.0.0.21 to cc:cc:cc:cc:cc:03 via eth0: wrong network segment\n"
    )

    config = parse(conf)
    current_leases = parse_leases(leases_text)
    lease_history = parse_lease_history(leases_text)
    events = parse_dhcp_log(events_text)
    devices = build_devices(config, current_leases, lease_history, events)
    return {device.mac: device for device in devices}


def test_device_discovered_from_active_lease():
    now = datetime.now()
    by_mac = _build(now)
    device = by_mac["cc:cc:cc:cc:cc:03"]
    assert device.current_lease is not None
    assert device.current_lease.ip == "10.0.0.21"
    assert device.hostname == "dynamic-device"


def test_device_with_reservation():
    now = datetime.now()
    by_mac = _build(now)
    device = by_mac["aa:aa:aa:aa:aa:01"]
    assert device.reservation is not None
    assert device.reservation.name == "res_a"
    assert device.current_ip == "10.0.0.20"
    assert device.status == DeviceStatus.ACTIVE


def test_device_with_no_reservation():
    now = datetime.now()
    by_mac = _build(now)
    device = by_mac["cc:cc:cc:cc:cc:03"]
    assert device.reservation is None


def test_device_discovered_purely_from_historical_lease_data_has_no_current_lease():
    now = datetime.now()
    by_mac = _build(now)
    # gg:...:07's block for 10.0.0.40 was superseded by hh:...:08's later block for the
    # same address, so it has no entry in "current" leases at all - only history.
    device = by_mac["gg:gg:gg:gg:gg:07"]
    assert device.current_lease is None
    assert device.reservation is None
    assert len(device.history) == 1
    assert device.history[0].ip == "10.0.0.40"
    assert device.status == DeviceStatus.INACTIVE
    assert "ago" in device.status_detail


def test_device_with_no_current_lease_status_detail_is_explainable():
    now = datetime.now()
    by_mac = _build(now)
    device = by_mac["gg:gg:gg:gg:gg:07"]
    assert device.status_detail.startswith("Inactive - last DHCP activity")


def test_multiple_historical_ips_for_one_mac():
    now = datetime.now()
    by_mac = _build(now)
    device = by_mac["ee:ee:ee:ee:ee:05"]
    assert device.current_ip == "10.0.0.31"
    assert device.previous_ips == ["10.0.0.30"]
    assert device.first_seen is not None and device.first_seen < now - timedelta(days=9)
    assert device.last_seen is not None and device.last_seen > now - timedelta(hours=4)


def test_device_lease_history_contains_every_record_newest_first():
    now = datetime.now()
    by_mac = _build(now)
    device = by_mac["ee:ee:ee:ee:ee:05"]
    assert [record.ip for record in device.history] == ["10.0.0.31", "10.0.0.30"]


def test_device_discovered_from_reservation_alone_with_only_log_activity():
    # DHCP activity itself is a router-level concern (filtered from the raw
    # event list by mac, not stored on Device - see test_devices_routes.py
    # for the "DHCP activity" section rendering); this just confirms a
    # device with no lease at all, only a reservation, is still discovered.
    config = parse(CONF)
    events = parse_dhcp_log("Sep  1 08:00:00 host dhcpd[1]: DHCPDISCOVER from aa:aa:aa:aa:aa:01 via eth0\n")
    devices = build_devices(config, [], [], events)
    device = find_device(devices, "aa:aa:aa:aa:aa:01")
    assert device is not None
    assert device.reservation is not None
    assert device.current_lease is None


def test_device_with_dhcp_errors_is_flagged_a_problem():
    now = datetime.now()
    by_mac = _build(now)
    device = by_mac["cc:cc:cc:cc:cc:03"]
    assert device.has_problem is True
    assert device.status == DeviceStatus.PROBLEM
    assert "DHCPNAK" in device.problem_summary


def test_denied_client_is_flagged_a_problem():
    now = datetime.now()
    by_mac = _build(now)
    device = by_mac["bb:bb:bb:bb:bb:02"]
    assert device.has_problem is True
    assert "denied" in device.problem_summary


def test_reservation_conflict_flags_both_macs_a_problem():
    conf = """
    subnet 10.0.0.0 netmask 255.255.255.0 {
        range 10.0.0.10 10.0.0.50;
        host a { hardware ethernet 11:11:11:11:11:11; fixed-address 10.0.0.5; }
        host b { hardware ethernet 22:22:22:22:22:22; fixed-address 10.0.0.5; }
    }
    """
    config = parse(conf)
    devices = build_devices(config, [], [], [])
    by_mac = {d.mac: d for d in devices}
    assert by_mac["11:11:11:11:11:11"].has_problem is True
    assert by_mac["22:22:22:22:22:22"].has_problem is True
    assert "conflict" in by_mac["11:11:11:11:11:11"].problem_summary


def test_device_with_insufficient_evidence_is_unknown_not_fabricated():
    # A reservation with a MAC that has never appeared in any lease record
    # and has no DHCP log activity - nothing to base "seen" evidence on.
    conf = "host lonely { hardware ethernet 33:33:33:33:33:33; fixed-address 10.0.0.9; }"
    config = parse(conf)
    devices = build_devices(config, [], [], [])
    device = find_device(devices, "33:33:33:33:33:33")
    assert device is not None
    assert device.first_seen is None
    assert device.last_seen is None
    assert device.status == DeviceStatus.RESERVED
    assert device.status_detail == "Reserved - no DHCP activity recorded"


def test_active_status_detail_reports_expiry():
    now = datetime.now()
    by_mac = _build(now)
    device = by_mac["aa:aa:aa:aa:aa:01"]
    assert device.status_detail.startswith("Active - lease expires in")


def test_recently_seen_vs_inactive_threshold():
    now = datetime.now()
    conf = "subnet 10.0.0.0 netmask 255.255.255.0 { range 10.0.0.10 10.0.0.50; }"
    config = parse(conf)

    recent_text = _block("10.0.0.15", "44:44:44:44:44:44", "free", now - RECENT_WINDOW + timedelta(minutes=5), now - RECENT_WINDOW + timedelta(hours=1))
    stale_text = _block("10.0.0.16", "55:55:55:55:55:55", "free", now - RECENT_WINDOW - timedelta(hours=1), now - RECENT_WINDOW - timedelta(minutes=30))

    recent_history = parse_lease_history(recent_text)
    stale_history = parse_lease_history(stale_text)
    devices = build_devices(config, [], recent_history + stale_history, [])
    by_mac = {d.mac: d for d in devices}

    assert by_mac["44:44:44:44:44:44"].status == DeviceStatus.RECENTLY_SEEN
    assert by_mac["55:55:55:55:55:55"].status == DeviceStatus.INACTIVE


def test_filter_by_reservation_and_lease():
    now = datetime.now()
    by_mac = _build(now)
    devices = list(by_mac.values())

    reserved_only = filter_devices(devices, reservation="yes")
    assert all(d.reservation for d in reserved_only)

    no_lease = filter_devices(devices, lease="no")
    assert all(d.current_lease is None for d in no_lease)


def test_filter_by_status_and_search():
    now = datetime.now()
    devices = list(_build(now).values())

    problems = filter_devices(devices, status="problem")
    assert {d.mac for d in problems} == {"cc:cc:cc:cc:cc:03", "bb:bb:bb:bb:bb:02"}

    by_ip = filter_devices(devices, q="10.0.0.20")
    assert {d.mac for d in by_ip} == {"aa:aa:aa:aa:aa:01"}


def test_find_device_normalizes_mac_case():
    now = datetime.now()
    devices = list(_build(now).values())
    assert find_device(devices, "AA:AA:AA:AA:AA:01") is not None


def test_sort_devices_default_prioritizes_problems_first():
    now = datetime.now()
    devices = list(_build(now).values())
    ordered = sort_devices(devices)
    assert ordered[0].status == DeviceStatus.PROBLEM


def test_sort_devices_by_mac_ascending_and_descending():
    now = datetime.now()
    devices = list(_build(now).values())

    ascending = [d.mac for d in sort_devices(devices, "mac")]
    assert ascending == sorted(ascending)

    descending = [d.mac for d in sort_devices(devices, "-mac")]
    assert descending == sorted(descending, reverse=True)
    assert descending == list(reversed(ascending))


def test_sort_devices_by_current_ip_is_numeric_not_lexical():
    now = datetime.now()
    devices = list(_build(now).values())
    ordered = sort_devices(devices, "current_ip")
    ips_with_address = [d.current_ip for d in ordered if d.current_ip]
    assert ips_with_address == ["10.0.0.20", "10.0.0.21", "10.0.0.23", "10.0.0.31", "10.0.0.40"]
    # devices with no current IP (gg:...:07, discovered only from history) sort last.
    assert ordered[-1].current_ip is None


def test_sort_devices_unknown_key_is_a_no_op_not_an_error():
    now = datetime.now()
    devices = list(_build(now).values())
    result = sort_devices(devices, "not-a-real-column")
    assert {d.mac for d in result} == {d.mac for d in devices}


def test_large_device_inventory_is_built_correctly_and_reasonably_fast():
    import time

    now = datetime.now()
    conf_lines = ["subnet 10.0.0.0 netmask 255.0.0.0 { range 10.0.0.1 10.255.255.254; }"]
    lease_blocks = []
    for i in range(2000):
        mac = f"aa:bb:cc:{(i >> 16) & 0xFF:02x}:{(i >> 8) & 0xFF:02x}:{i & 0xFF:02x}"
        ip = f"10.0.{(i // 254) % 255}.{(i % 254) + 1}"
        state = "active" if i % 3 == 0 else "free"
        lease_blocks.append(_block(ip, mac, state, now - timedelta(hours=1), now + timedelta(hours=1)))

    config = parse("\n".join(conf_lines))
    leases_text = "".join(lease_blocks)
    current_leases = parse_leases(leases_text)
    lease_history = parse_lease_history(leases_text)

    start = time.monotonic()
    devices = build_devices(config, current_leases, lease_history, [])
    elapsed = time.monotonic() - start

    assert len(devices) == 2000
    assert elapsed < 5.0
    active_count = sum(1 for d in devices if d.status == DeviceStatus.ACTIVE)
    assert active_count > 0
