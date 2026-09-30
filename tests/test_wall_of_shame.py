from datetime import datetime, timedelta

from sandia.devices import build_devices
from sandia.dhcpd import parse
from sandia.diagnostics.dhcp_log import parse_dhcp_log
from sandia.leases import parse_lease_history
from sandia.wall_of_shame import (
    parse_syslog_timestamp,
    top_abandoned,
    top_ip_changers,
    top_nak_devices,
)


def _log_line(dt: datetime, message: str) -> str:
    return f"{dt.strftime('%b %d %H:%M:%S')} host dhcpd[1]: {message}\n"


def _lease_block(ip: str, mac: str, state: str, starts: datetime) -> str:
    return f"lease {ip} {{\n  starts {starts.isoweekday() % 7} {starts.strftime('%Y/%m/%d %H:%M:%S')};\n  binding state {state};\n  hardware ethernet {mac};\n}}\n"


CONF = "subnet 10.0.0.0 netmask 255.255.255.0 { range 10.0.0.10 10.0.0.50; }"


def test_dhcpnak_counts_are_correct():
    now = datetime.now()
    log = (
        _log_line(now - timedelta(hours=1), "DHCPNAK on 10.0.0.11 to aa:aa:aa:aa:aa:01 via eth0")
        + _log_line(now - timedelta(hours=5), "DHCPNAK on 10.0.0.11 to aa:aa:aa:aa:aa:01 via eth0")
        + _log_line(now - timedelta(hours=2), "DHCPNAK on 10.0.0.12 to bb:bb:bb:bb:bb:02 via eth0")
    )
    events = parse_dhcp_log(log)
    entries = top_nak_devices(events, [], now, "all")
    counts = {e.mac: e.count for e in entries}
    assert counts == {"aa:aa:aa:aa:aa:01": 2, "bb:bb:bb:bb:bb:02": 1}


def test_dhcpnak_last_nak_is_the_most_recent_one():
    now = datetime.now()
    older = now - timedelta(hours=5)
    newer = now - timedelta(hours=1)
    log = (
        _log_line(older, "DHCPNAK on 10.0.0.11 to aa:aa:aa:aa:aa:01 via eth0")
        + _log_line(newer, "DHCPNAK on 10.0.0.11 to aa:aa:aa:aa:aa:01 via eth0")
    )
    events = parse_dhcp_log(log)
    entries = top_nak_devices(events, [], now, "all")
    assert entries[0].last_nak.replace(microsecond=0) == newer.replace(microsecond=0)


def test_dhcpnak_time_filtering_24h_vs_7d_vs_all():
    now = datetime.now()
    log = (
        _log_line(now - timedelta(hours=1), "DHCPNAK on 10.0.0.11 to aa:aa:aa:aa:aa:01 via eth0")
        + _log_line(now - timedelta(hours=5), "DHCPNAK on 10.0.0.11 to aa:aa:aa:aa:aa:01 via eth0")
        + _log_line(now - timedelta(days=3), "DHCPNAK on 10.0.0.11 to aa:aa:aa:aa:aa:01 via eth0")
        + _log_line(now - timedelta(days=10), "DHCPNAK on 10.0.0.12 to bb:bb:bb:bb:bb:02 via eth0")
    )
    events = parse_dhcp_log(log)

    day = top_nak_devices(events, [], now, "24h")
    assert {e.mac: e.count for e in day} == {"aa:aa:aa:aa:aa:01": 2}

    week = top_nak_devices(events, [], now, "7d")
    assert {e.mac: e.count for e in week} == {"aa:aa:aa:aa:aa:01": 3}

    everything = top_nak_devices(events, [], now, "all")
    assert {e.mac: e.count for e in everything} == {"aa:aa:aa:aa:aa:01": 3, "bb:bb:bb:bb:bb:02": 1}


def test_dhcpnak_device_with_no_naks_is_not_shown():
    now = datetime.now()
    config = parse("host res { hardware ethernet cc:cc:cc:cc:cc:03; fixed-address 10.0.0.20; }")
    devices = build_devices(config, [], [], [])
    log = _log_line(now, "DHCPNAK on 10.0.0.11 to aa:aa:aa:aa:aa:01 via eth0")
    entries = top_nak_devices(parse_dhcp_log(log), devices, now, "all")
    assert "cc:cc:cc:cc:cc:03" not in {e.mac for e in entries}


def test_dhcpnak_empty_events_returns_empty_list():
    now = datetime.now()
    assert top_nak_devices([], [], now, "all") == []


def test_parse_syslog_timestamp_rolls_back_year_near_boundary():
    now = datetime(2026, 1, 3, 8, 0, 0)
    # "Dec 30" with no year, assumed current year (2026), would be in the
    # future relative to "now" (Jan 3 2026) - must roll back to 2025.
    parsed = parse_syslog_timestamp("Dec 30 10:00:00", now)
    assert parsed.year == 2025


def test_ip_change_counts_are_correct_and_renewals_dont_count():
    now = datetime.now()
    mac = "aa:aa:aa:aa:aa:01"
    text = (
        _lease_block("10.0.0.11", mac, "free", now - timedelta(days=10))
        + _lease_block("10.0.0.11", mac, "free", now - timedelta(days=9))  # renewal, same IP - not a change
        + _lease_block("10.0.0.12", mac, "free", now - timedelta(days=5))  # change #1
        + _lease_block("10.0.0.12", mac, "active", now - timedelta(days=4))  # renewal - not a change
        + _lease_block("10.0.0.13", mac, "active", now - timedelta(days=1))  # change #2
    )
    history = parse_lease_history(text)
    entries = top_ip_changers(history, [], now, "all")
    assert len(entries) == 1
    assert entries[0].mac == mac
    assert entries[0].count == 2


def test_ip_change_time_filtering():
    now = datetime.now()
    mac = "aa:aa:aa:aa:aa:01"
    text = (
        _lease_block("10.0.0.11", mac, "free", now - timedelta(days=10))
        + _lease_block("10.0.0.12", mac, "free", now - timedelta(hours=2))  # change within 24h
    )
    history = parse_lease_history(text)
    entries = top_ip_changers(history, [], now, "24h")
    assert len(entries) == 1
    assert entries[0].count == 1


def test_ip_change_device_with_single_ip_ever_is_not_shown():
    now = datetime.now()
    mac = "aa:aa:aa:aa:aa:01"
    text = _lease_block("10.0.0.11", mac, "active", now - timedelta(days=1))
    history = parse_lease_history(text)
    entries = top_ip_changers(history, [], now, "all")
    assert entries == []


def test_ip_change_empty_history_returns_empty_list():
    now = datetime.now()
    assert top_ip_changers([], [], now, "all") == []


def test_abandoned_counts_are_correct():
    now = datetime.now()
    mac = "aa:aa:aa:aa:aa:01"
    text = (
        _lease_block("10.0.0.11", mac, "abandoned", now - timedelta(days=1))
        + _lease_block("10.0.0.11", mac, "abandoned", now - timedelta(hours=2))
        + _lease_block("10.0.0.12", "bb:bb:bb:bb:bb:02", "active", now)  # not abandoned - excluded
    )
    history = parse_lease_history(text)
    config = parse(CONF)
    entries = top_abandoned(history, [], config, now, "all")
    assert len(entries) == 1
    assert entries[0].mac == mac
    assert entries[0].count == 2


def test_abandoned_lease_with_no_mac_shows_ip_not_a_fabricated_device():
    now = datetime.now()
    text = f"lease 10.0.0.30 {{\n  starts 3 {now:%Y/%m/%d %H:%M:%S};\n  binding state abandoned;\n}}\n"
    history = parse_lease_history(text)
    config = parse(CONF)
    entries = top_abandoned(history, [], config, now, "all")
    assert len(entries) == 1
    assert entries[0].mac is None
    assert entries[0].device is None
    assert entries[0].ip == "10.0.0.30"


def test_abandoned_time_filtering():
    now = datetime.now()
    mac = "aa:aa:aa:aa:aa:01"
    text = (
        _lease_block("10.0.0.11", mac, "abandoned", now - timedelta(days=10))
        + _lease_block("10.0.0.11", mac, "abandoned", now - timedelta(hours=1))
    )
    history = parse_lease_history(text)
    config = parse(CONF)
    entries = top_abandoned(history, [], config, now, "24h")
    assert entries[0].count == 1


def test_abandoned_empty_history_returns_empty_list():
    now = datetime.now()
    config = parse(CONF)
    assert top_abandoned([], [], config, now, "all") == []


def test_abandoned_resolves_subnet_for_navigation():
    now = datetime.now()
    text = _lease_block("10.0.0.11", "aa:aa:aa:aa:aa:01", "abandoned", now)
    history = parse_lease_history(text)
    config = parse(CONF)
    entries = top_abandoned(history, [], config, now, "all")
    assert entries[0].subnet_key == "10.0.0.0_255.255.255.0"
