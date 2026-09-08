from sandia.dhcpd import parse
from sandia.diagnostics.client import diagnose_client
from sandia.diagnostics.dhcp_log import parse_dhcp_log
from sandia.diagnostics.models import Confidence, Status
from sandia.leases import parse_leases

CONF = """
subnet 192.168.1.0 netmask 255.255.255.0 {
    range 192.168.1.100 192.168.1.101;
    host printer {
        hardware ethernet aa:aa:aa:aa:aa:01;
        fixed-address 192.168.1.50;
    }
}
"""


def _config():
    return parse(CONF)


def test_active_client_is_healthy():
    config = _config()
    leases = parse_leases("lease 192.168.1.50 {\n  binding state active;\n  hardware ethernet aa:aa:aa:aa:aa:01;\n}\n")
    result = diagnose_client(config, leases, [], None, mac="aa:aa:aa:aa:aa:01")

    assert result.status == Status.HEALTHY
    assert result.findings[0].problem == "Client has a valid, active lease"
    lease_step = next(s for s in result.steps if s.name == "Lease")
    assert lease_step.status == Status.HEALTHY


def test_client_with_no_lease_is_unknown_not_a_false_positive():
    config = _config()  # printer reservation exists, but no matching lease and no log activity
    result = diagnose_client(config, [], [], None, mac="aa:aa:aa:aa:aa:01")

    assert result.status == Status.UNKNOWN
    finding = result.findings[0]
    assert finding.confidence == Confidence.UNKNOWN
    assert "no active lease" in finding.problem.lower() or "no evidence" in finding.root_cause.lower()


def test_insufficient_evidence_when_nothing_identifies_the_client():
    config = _config()
    result = diagnose_client(config, [], [], None, mac="ff:ff:ff:ff:ff:ff")  # matches nothing at all

    assert result.status == Status.UNKNOWN
    assert result.findings[0].problem == "Insufficient evidence"
    assert result.findings[0].confidence == Confidence.UNKNOWN


def test_insufficient_evidence_with_no_identifiers_at_all():
    config = _config()
    result = diagnose_client(config, [], [], None)

    assert result.status == Status.UNKNOWN
    assert result.findings[0].problem == "Insufficient evidence"


def test_dhcpnak_is_detected_as_critical_root_cause():
    config = _config()
    log = "Sep  2 11:05:12 host dhcpd[1]: DHCPNAK on 192.168.1.220 to aa:bb:cc:00:11:22 via eth0: wrong network segment\n"
    events = parse_dhcp_log(log)

    result = diagnose_client(config, [], events, None, mac="aa:bb:cc:00:11:22")

    assert result.status == Status.CRITICAL
    finding = result.findings[0]
    assert finding.problem == "dhcpd sent DHCPNAK"
    assert finding.root_cause == "wrong network segment"
    assert finding.confidence == Confidence.CONFIRMED


def test_dhcpnak_without_reason_text_is_strong_not_confirmed():
    config = _config()
    log = "Sep  2 11:05:12 host dhcpd[1]: DHCPNAK on 192.168.1.220 to aa:bb:cc:00:11:22 via eth0\n"
    events = parse_dhcp_log(log)

    result = diagnose_client(config, [], events, None, mac="aa:bb:cc:00:11:22")

    finding = result.findings[0]
    assert finding.confidence == Confidence.STRONG


def test_pool_exhaustion_surfaces_as_client_root_cause_for_unreserved_client():
    config = _config()  # pool is 192.168.1.100-101, 2 addresses
    leases = parse_leases(
        "lease 192.168.1.100 {\n  binding state active;\n  hardware ethernet bb:bb:bb:bb:bb:01;\n}\n"
        "lease 192.168.1.101 {\n  binding state active;\n  hardware ethernet bb:bb:bb:bb:bb:02;\n}\n"
    )
    # a third, unreserved client trying to get an address on the same subnet
    # (192.168.1.105 is unused but still within the subnet's network, so
    # subnet resolution succeeds without colliding with either existing lease)
    result = diagnose_client(config, leases, [], None, mac="cc:cc:cc:cc:cc:cc", ip="192.168.1.105")

    assert result.status == Status.CRITICAL
    assert result.findings[0].problem == "DHCP pool exhausted"


def test_ip_conflict_between_reservation_and_active_lease_is_critical():
    config = _config()  # printer reserved to 192.168.1.50 with mac aa:aa:aa:aa:aa:01
    leases = parse_leases("lease 192.168.1.50 {\n  binding state active;\n  hardware ethernet 99:99:99:99:99:99;\n}\n")

    result = diagnose_client(config, leases, [], None, mac="aa:aa:aa:aa:aa:01")

    assert result.status == Status.CRITICAL
    finding = result.findings[0]
    assert finding.problem == "Reserved address is in use by another client"
    assert finding.confidence == Confidence.CONFIRMED


def test_ip_not_covered_by_any_subnet_is_warning():
    config = _config()
    result = diagnose_client(config, [], [], None, ip="10.99.99.99")

    assert result.status == Status.WARNING
    assert result.findings[0].problem == "Address not covered by any configured subnet"


def test_discover_without_offer_is_possible_confidence_when_no_reason():
    config = _config()
    log = "Sep  2 09:00:00 host dhcpd[1]: DHCPDISCOVER from dd:dd:dd:dd:dd:dd via eth0\n"
    events = parse_dhcp_log(log)

    result = diagnose_client(config, [], events, None, mac="dd:dd:dd:dd:dd:dd", ip="192.168.1.100")

    finding = result.findings[0]
    assert finding.problem == "No DHCPOFFER followed this client's DHCPDISCOVER"
    assert finding.confidence == Confidence.POSSIBLE


def test_log_unavailable_is_reflected_in_activity_step_not_treated_as_no_activity():
    config = _config()
    result = diagnose_client(config, [], [], "DHCP log not found at /var/log/syslog", mac="aa:aa:aa:aa:aa:01")

    activity_step = next(s for s in result.steps if s.name == "DHCP activity")
    assert activity_step.status == Status.UNKNOWN
    assert "not found" in activity_step.detail


def test_flow_steps_are_always_present_and_in_order():
    config = _config()
    result = diagnose_client(config, [], [], None, mac="aa:aa:aa:aa:aa:01")
    assert [s.name for s in result.steps] == [
        "Client",
        "DHCP activity",
        "Subnet selection",
        "Reservation lookup",
        "Pool selection",
        "Address availability",
        "DHCP response",
        "Lease",
    ]


def test_never_reports_a_critical_or_warning_finding_without_evidence_or_confidence():
    # Invariant check across every scenario this file exercises: a
    # CRITICAL/WARNING finding must carry actual evidence and a confidence
    # level other than UNKNOWN - "unknown confidence" and "critical" is a
    # contradiction (that's what Status.UNKNOWN findings are for instead).
    scenarios = [
        diagnose_client(_config(), [], [], None, mac="aa:aa:aa:aa:aa:01"),
        diagnose_client(
            _config(),
            parse_leases("lease 192.168.1.50 {\n  binding state active;\n  hardware ethernet aa:aa:aa:aa:aa:01;\n}\n"),
            [],
            None,
            mac="aa:aa:aa:aa:aa:01",
        ),
        diagnose_client(_config(), [], [], None, mac="ff:ff:ff:ff:ff:ff"),
        diagnose_client(_config(), [], [], None),
        diagnose_client(_config(), [], [], None, ip="10.99.99.99"),
        diagnose_client(
            _config(),
            parse_leases("lease 192.168.1.50 {\n  binding state active;\n  hardware ethernet 99:99:99:99:99:99;\n}\n"),
            [],
            None,
            mac="aa:aa:aa:aa:aa:01",
        ),
        diagnose_client(
            _config(),
            [],
            parse_dhcp_log("Sep  2 11:05:12 host dhcpd[1]: DHCPNAK on 192.168.1.220 to aa:bb:cc:00:11:22 via eth0: wrong network segment\n"),
            None,
            mac="aa:bb:cc:00:11:22",
        ),
    ]
    for result in scenarios:
        for finding in result.findings:
            if finding.status in (Status.CRITICAL, Status.WARNING):
                assert finding.confidence != Confidence.UNKNOWN, finding.problem
                assert finding.root_cause or finding.evidence, finding.problem
