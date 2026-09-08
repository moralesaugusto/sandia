from sandia.dhcpd import parse
from sandia.ip_map import MAX_CELLS, build_subnet_map, find_cell
from sandia.leases import parse_leases

CONF = """
subnet 192.168.9.0 netmask 255.255.255.0 {
    range 192.168.9.10 192.168.9.15;
    host res10 {
        hardware ethernet aa:aa:aa:aa:aa:01;
        fixed-address 192.168.9.10;
    }
    host res11 {
        hardware ethernet aa:aa:aa:aa:aa:02;
        fixed-address 192.168.9.11;
    }
}
host deny-aaaaaaaaaa04 {
    hardware ethernet aa:aa:aa:aa:aa:04;
    deny booting;
}
"""

LEASES = """
lease 192.168.9.11 {
  binding state active;
  hardware ethernet aa:aa:aa:aa:aa:02;
}
lease 192.168.9.12 {
  binding state active;
  hardware ethernet aa:aa:aa:aa:aa:03;
}
lease 192.168.9.13 {
  binding state active;
  hardware ethernet aa:aa:aa:aa:aa:04;
}
"""


def _build():
    config = parse(CONF)
    leases = parse_leases(LEASES)
    subnet = config.find_subnet("192.168.9.0_255.255.255.0")
    return config, subnet, leases


def test_cell_statuses_cover_every_case():
    config, subnet, leases = _build()
    subnet_map = build_subnet_map(config, subnet, leases)

    by_ip = {cell.ip: cell for cell in subnet_map.cells}
    assert by_ip["192.168.9.10"].status == "reserved"
    assert by_ip["192.168.9.11"].status == "reserved-online"
    assert by_ip["192.168.9.12"].status == "leased"
    assert by_ip["192.168.9.13"].status == "denied"
    assert by_ip["192.168.9.14"].status == "free"
    assert by_ip["192.168.9.15"].status == "free"


def test_total_and_grid_dimensions():
    config, subnet, leases = _build()
    subnet_map = build_subnet_map(config, subnet, leases)

    assert subnet_map.total == 6
    assert subnet_map.too_large is False
    assert subnet_map.columns * subnet_map.rows >= subnet_map.total


def test_reservation_outside_pool_range_is_listed_separately():
    config = parse(
        """
        subnet 10.0.0.0 netmask 255.255.255.0 {
            range 10.0.0.100 10.0.0.110;
            host outsider {
                hardware ethernet bb:bb:bb:bb:bb:01;
                fixed-address 10.0.0.5;
            }
        }
        """
    )
    subnet = config.find_subnet("10.0.0.0_255.255.255.0")
    subnet_map = build_subnet_map(config, subnet, [])

    assert [host.name for host in subnet_map.outside_range] == ["outsider"]
    assert all(cell.host is None for cell in subnet_map.cells)


def test_subnet_with_no_range_has_no_cells():
    config = parse("subnet 10.0.0.0 netmask 255.255.255.0 { }")
    subnet = config.find_subnet("10.0.0.0_255.255.255.0")
    subnet_map = build_subnet_map(config, subnet, [])

    assert subnet_map.total == 0
    assert subnet_map.cells == []


def test_pool_larger_than_cap_skips_cell_rendering():
    # A /20 (4096 addresses) exceeds the cap.
    config = parse("subnet 10.0.0.0 netmask 255.255.240.0 { range 10.0.0.0 10.0.15.255; }")
    subnet = config.find_subnet("10.0.0.0_255.255.240.0")
    subnet_map = build_subnet_map(config, subnet, [])

    assert subnet_map.total == 4096
    assert subnet_map.total > MAX_CELLS
    assert subnet_map.too_large is True
    assert subnet_map.cells == []


def test_find_cell_returns_matching_cell():
    config, subnet, leases = _build()
    cell = find_cell(config, subnet, leases, "192.168.9.12")
    assert cell is not None
    assert cell.status == "leased"
    assert cell.lease.mac == "aa:aa:aa:aa:aa:03"


def test_find_cell_returns_none_for_ip_outside_range():
    config, subnet, leases = _build()
    assert find_cell(config, subnet, leases, "192.168.9.99") is None
