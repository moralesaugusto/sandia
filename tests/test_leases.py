from pathlib import Path

from sandia.leases import parse_leases

FIXTURE = Path(__file__).parent / "fixtures" / "sample_dhcpd.leases"


def test_parses_all_leases_keyed_by_ip():
    leases = parse_leases(FIXTURE.read_text())
    by_ip = {lease.ip: lease for lease in leases}

    assert set(by_ip) == {"192.168.1.50", "192.168.1.51", "192.168.1.52"}


def test_later_block_supersedes_earlier_one_for_same_ip():
    leases = parse_leases(FIXTURE.read_text())
    by_ip = {lease.ip: lease for lease in leases}

    lease = by_ip["192.168.1.50"]
    assert lease.starts == "3 2026/09/02 22:00:01"
    assert lease.is_active


def test_fields_extracted_correctly():
    leases = parse_leases(FIXTURE.read_text())
    by_ip = {lease.ip: lease for lease in leases}

    active = by_ip["192.168.1.50"]
    assert active.mac == "00:11:22:33:44:55"
    assert active.hostname == "printer"
    assert active.binding_state == "active"

    free = by_ip["192.168.1.51"]
    assert free.mac == "aa:bb:cc:dd:ee:01"
    assert free.hostname is None
    assert free.binding_state == "free"
    assert not free.is_active


def test_missing_file_returns_empty_list(tmp_path):
    from sandia.leases import load_leases

    assert load_leases(tmp_path / "does-not-exist.leases") == []
