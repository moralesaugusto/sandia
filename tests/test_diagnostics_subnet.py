from sandia.dhcpd import parse
from sandia.diagnostics.models import Status
from sandia.diagnostics.subnet import diagnose_subnet
from sandia.leases import parse_leases


def _diagnose(conf: str, leases_text: str = "", configured_interfaces: list[str] | None = None, key: str = "10.0.0.0_255.255.255.0"):
    config = parse(conf)
    leases = parse_leases(leases_text) if leases_text else []
    subnet = config.find_subnet(key)
    result = diagnose_subnet(config, subnet, leases, configured_interfaces or [])
    return result


def _lease(ip: str, mac: str, state: str = "active") -> str:
    return f"lease {ip} {{\n  binding state {state};\n  hardware ethernet {mac};\n}}\n"


def test_healthy_subnet_reports_no_issues():
    result = _diagnose("subnet 10.0.0.0 netmask 255.255.255.0 { range 10.0.0.10 10.0.0.20; }")
    assert result.status == Status.HEALTHY
    assert result.findings[0].problem == "No issues detected"


def test_pool_exhaustion_is_critical_with_expected_evidence_shape():
    conf = "subnet 10.0.0.0 netmask 255.255.255.0 { range 10.0.0.10 10.0.0.12; }"  # 3 addresses
    leases = "".join(_lease(ip, f"aa:bb:cc:dd:ee:0{i}") for i, ip in enumerate(["10.0.0.10", "10.0.0.11", "10.0.0.12"], start=1))
    result = _diagnose(conf, leases)

    assert result.status == Status.CRITICAL
    finding = next(f for f in result.findings if f.problem == "DHCP pool exhausted")
    evidence = {e.label: e.value for e in finding.evidence}
    assert evidence["Usable"] == "3"
    assert evidence["Allocated"] == "3"
    assert evidence["Available"] == "0"


def test_high_utilization_is_warning_not_critical():
    conf = "subnet 10.0.0.0 netmask 255.255.255.0 { range 10.0.0.1 10.0.0.10; }"  # 10 addresses
    leases = "".join(_lease(f"10.0.0.{i}", f"aa:bb:cc:dd:ee:0{i}") for i in range(1, 10))  # 9/10 = 90%
    result = _diagnose(conf, leases)

    finding = next(f for f in result.findings if f.problem == "High pool utilization")
    assert finding.status == Status.WARNING
    assert result.status == Status.WARNING


def test_low_utilization_is_healthy():
    conf = "subnet 10.0.0.0 netmask 255.255.255.0 { range 10.0.0.1 10.0.0.10; }"
    leases = _lease("10.0.0.1", "aa:bb:cc:dd:ee:01")
    result = _diagnose(conf, leases)
    assert result.status == Status.HEALTHY


def test_abandoned_leases_reported():
    conf = "subnet 10.0.0.0 netmask 255.255.255.0 { range 10.0.0.1 10.0.0.10; }"
    leases = _lease("10.0.0.5", "aa:bb:cc:dd:ee:05", state="abandoned")
    result = _diagnose(conf, leases)

    finding = next(f for f in result.findings if "abandoned" in f.problem)
    assert finding.status == Status.WARNING
    assert "10.0.0.5" in finding.evidence[0].value


def test_no_range_configured_is_warning():
    result = _diagnose("subnet 10.0.0.0 netmask 255.255.255.0 { }")
    assert result.status == Status.WARNING
    assert any("No pool range" in f.problem for f in result.findings)


def test_backwards_range_is_critical():
    result = _diagnose("subnet 10.0.0.0 netmask 255.255.255.0 { range 10.0.0.20 10.0.0.10; }")
    assert result.status == Status.CRITICAL
    assert any("backwards" in f.problem for f in result.findings)


def test_range_outside_network_is_critical():
    result = _diagnose("subnet 10.0.0.0 netmask 255.255.255.0 { range 10.0.1.10 10.0.1.20; }")
    assert result.status == Status.CRITICAL
    assert any("outside subnet network" in f.problem for f in result.findings)


def test_duplicate_reservation_ip_is_critical():
    conf = """
    subnet 10.0.0.0 netmask 255.255.255.0 {
        range 10.0.0.50 10.0.0.60;
        host a { hardware ethernet aa:aa:aa:aa:aa:01; fixed-address 10.0.0.5; }
        host b { hardware ethernet aa:aa:aa:aa:aa:02; fixed-address 10.0.0.5; }
    }
    """
    result = _diagnose(conf)
    finding = next(f for f in result.findings if f.problem == "Duplicate reservation IP address")
    assert finding.status == Status.CRITICAL
    assert "a" in finding.evidence[1].value and "b" in finding.evidence[1].value


def test_duplicate_reservation_mac_is_critical():
    conf = """
    subnet 10.0.0.0 netmask 255.255.255.0 {
        range 10.0.0.50 10.0.0.60;
        host a { hardware ethernet aa:aa:aa:aa:aa:01; fixed-address 10.0.0.5; }
        host b { hardware ethernet aa:aa:aa:aa:aa:01; fixed-address 10.0.0.6; }
    }
    """
    result = _diagnose(conf)
    assert any(f.problem == "Duplicate reservation MAC address" for f in result.findings)


def test_reservation_missing_mac_is_warning():
    conf = """
    subnet 10.0.0.0 netmask 255.255.255.0 {
        range 10.0.0.50 10.0.0.60;
        host a { fixed-address 10.0.0.5; }
    }
    """
    result = _diagnose(conf)
    assert any(f.problem == "Reservation has no MAC address" for f in result.findings)


def test_reservation_missing_fixed_address_is_warning():
    conf = """
    subnet 10.0.0.0 netmask 255.255.255.0 {
        range 10.0.0.50 10.0.0.60;
        host a { hardware ethernet aa:aa:aa:aa:aa:01; }
    }
    """
    result = _diagnose(conf)
    assert any(f.problem == "Reservation has no fixed address" for f in result.findings)


def test_reservation_address_outside_network_is_warning():
    conf = """
    subnet 10.0.0.0 netmask 255.255.255.0 {
        range 10.0.0.50 10.0.0.60;
        host a { hardware ethernet aa:aa:aa:aa:aa:01; fixed-address 192.168.1.5; }
    }
    """
    result = _diagnose(conf)
    finding = next(f for f in result.findings if f.problem == "Reservation address outside subnet network")
    assert finding.status == Status.WARNING


def test_overlapping_pools_is_critical():
    conf = """
    subnet 10.0.0.0 netmask 255.255.255.0 { range 10.0.0.10 10.0.0.30; }
    subnet 10.0.1.0 netmask 255.255.255.0 { range 10.0.0.20 10.0.0.40; }
    """
    result = _diagnose(conf)
    assert result.status == Status.CRITICAL
    assert any("overlaps" in f.root_cause for f in result.findings)


def test_interface_tag_mismatch_is_warning():
    conf = """
    # interface: eth5
    subnet 10.0.0.0 netmask 255.255.255.0 { range 10.0.0.10 10.0.0.20; }
    """
    result = _diagnose(conf, configured_interfaces=["eth0", "eth1"])
    finding = next(f for f in result.findings if "interface" in f.problem.lower())
    assert finding.status == Status.WARNING
    assert "eth5" in finding.evidence[0].value


def test_matching_interface_tag_is_not_flagged():
    conf = """
    # interface: eth0
    subnet 10.0.0.0 netmask 255.255.255.0 { range 10.0.0.10 10.0.0.20; }
    """
    result = _diagnose(conf, configured_interfaces=["eth0", "eth1"])
    assert result.status == Status.HEALTHY
