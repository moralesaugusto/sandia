from pathlib import Path

from sandia.config import Settings
from sandia.diagnostics.dhcp_log import error_like_lines, events_for, load_dhcp_events, parse_dhcp_log

SAMPLE = """\
Sep  2 09:15:00 host dhcpd[1234]: DHCPDISCOVER from aa:bb:cc:dd:ee:ff via eth0
Sep  2 09:15:00 host dhcpd[1234]: DHCPOFFER on 192.168.1.101 to aa:bb:cc:dd:ee:ff via eth0
Sep  2 09:15:01 host dhcpd[1234]: DHCPREQUEST for 192.168.1.101 (192.168.1.1) from aa:bb:cc:dd:ee:ff via eth0
Sep  2 09:15:01 host dhcpd[1234]: DHCPACK on 192.168.1.101 to aa:bb:cc:dd:ee:ff via eth0
Sep  2 11:05:12 host dhcpd[1234]: DHCPNAK on 192.168.1.220 to aa:bb:cc:00:11:22 via eth0: wrong network segment
Sep  2 12:40:07 host dhcpd[1234]: DHCPDISCOVER from de:ad:be:ef:00:01 via eth1: no free leases
Sep  2 12:41:00 host dhcpd[1234]: Configuration file errors encountered -- exiting
Sep  2 12:42:00 host kernel: unrelated non-dhcpd line mentioning error should be ignored
"""


def test_parses_known_event_types_with_fields():
    events = parse_dhcp_log(SAMPLE)
    by_kind = {}
    for event in events:
        by_kind.setdefault(event.kind, []).append(event)

    discover = by_kind["DHCPDISCOVER"][0]
    assert discover.mac == "aa:bb:cc:dd:ee:ff"
    assert discover.iface == "eth0"

    offer = by_kind["DHCPOFFER"][0]
    assert offer.ip == "192.168.1.101"
    assert offer.mac == "aa:bb:cc:dd:ee:ff"

    ack = by_kind["DHCPACK"][0]
    assert ack.ip == "192.168.1.101"

    nak = by_kind["DHCPNAK"][0]
    assert nak.ip == "192.168.1.220"
    assert nak.mac == "aa:bb:cc:00:11:22"
    assert nak.reason == "wrong network segment"

    exhausted = by_kind["DHCPDISCOVER"][1]
    assert exhausted.mac == "de:ad:be:ef:00:01"
    assert exhausted.reason == "no free leases"


def test_unrecognized_dhcpd_line_is_kept_as_other():
    events = parse_dhcp_log(SAMPLE)
    other = [e for e in events if e.kind == "OTHER"]
    assert len(other) == 1
    assert "Configuration file errors" in other[0].raw


def test_non_dhcpd_lines_are_ignored():
    events = parse_dhcp_log(SAMPLE)
    assert not any("kernel" in e.raw for e in events)


def test_load_dhcp_events_missing_file_reports_reason(tmp_path):
    settings = Settings(data_dir=tmp_path, dhcp_log_path=tmp_path / "does-not-exist.log")
    events, reason = load_dhcp_events(settings)
    assert events == []
    assert reason is not None
    assert "not found" in reason


def test_load_dhcp_events_reads_existing_file(tmp_path):
    log_path = tmp_path / "dhcpd.log"
    log_path.write_text(SAMPLE)
    settings = Settings(data_dir=tmp_path, dhcp_log_path=log_path)

    events, reason = load_dhcp_events(settings)
    assert reason is None
    assert len(events) > 0


def test_load_dhcp_events_unreadable_file_reports_reason(tmp_path, monkeypatch):
    log_path = tmp_path / "dhcpd.log"
    log_path.write_text(SAMPLE)
    settings = Settings(data_dir=tmp_path, dhcp_log_path=log_path)

    # Patch open() (not stat()/exists()) so the file is still seen to exist -
    # this exercises the "exists but can't be read" branch specifically.
    original_open = Path.open

    def fake_open(self, *args, **kwargs):
        if self == log_path:
            raise PermissionError("denied")
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fake_open)

    events, reason = load_dhcp_events(settings)
    assert events == []
    assert reason is not None
    assert "not readable" in reason


def test_events_for_filters_by_mac_and_excludes_other():
    events = parse_dhcp_log(SAMPLE)
    matches = events_for(events, mac="aa:bb:cc:dd:ee:ff", ip=None)
    assert len(matches) == 4
    assert all(e.kind != "OTHER" for e in matches)


def test_events_for_filters_by_ip():
    events = parse_dhcp_log(SAMPLE)
    matches = events_for(events, mac=None, ip="192.168.1.220")
    assert len(matches) == 1
    assert matches[0].kind == "DHCPNAK"


def test_events_for_returns_empty_without_identifiers():
    events = parse_dhcp_log(SAMPLE)
    assert events_for(events, mac=None, ip=None) == []


def test_error_like_lines_finds_keyword_matches():
    events = parse_dhcp_log(SAMPLE)
    matches = error_like_lines(events)
    raws = [e.raw for e in matches]
    assert any("no free leases" in raw for raw in raws)
    assert any("Configuration file errors" in raw for raw in raws)


def test_error_like_lines_respects_limit():
    events = parse_dhcp_log(SAMPLE)
    matches = error_like_lines(events, limit=1)
    assert len(matches) == 1
