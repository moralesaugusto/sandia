import copy
import json

from sandia.change_impact import (
    RISK_HIGH,
    RISK_LOW,
    RISK_REVIEW,
    analyze,
    impact_as_text,
)
from sandia.dhcpd import parse
from sandia.dhcpd.kea import parse_kea_config
from sandia.leases import Lease

BASE = {
    "Dhcp4": {
        "interfaces-config": {"interfaces": ["eth0"]},
        "valid-lifetime": 3600,
        "subnet4": [
            {
                "id": 1,
                "subnet": "192.0.2.0/24",
                "pools": [{"pool": "192.0.2.100 - 192.0.2.109"}],
                "option-data": [{"name": "routers", "data": "192.0.2.1"}],
                "reservations": [{"hostname": "printer", "hw-address": "aa:aa:aa:aa:aa:01", "ip-address": "192.0.2.50"}],
            },
            {"id": 2, "subnet": "198.51.100.0/24", "pools": [{"pool": "198.51.100.10 - 198.51.100.20"}]},
        ],
    }
}


def _lease(ip, mac, state="active"):
    return Lease(ip=ip, mac=mac, hostname=None, starts=None, ends=None, binding_state=state)


LEASES = [
    _lease("192.0.2.100", "bb:bb:bb:bb:bb:01"),
    _lease("192.0.2.101", "bb:bb:bb:bb:bb:02"),
    _lease("198.51.100.10", "bb:bb:bb:bb:bb:03"),
    _lease("192.0.2.105", "bb:bb:bb:bb:bb:09", state="free"),
]


def _run(change, leases=LEASES):
    new = copy.deepcopy(BASE)
    change(new["Dhcp4"])
    old_config = parse_kea_config(json.dumps(BASE))
    new_config = parse_kea_config(json.dumps(new))
    return analyze(
        old_config,
        new_config,
        leases,
        BASE["Dhcp4"]["interfaces-config"]["interfaces"],
        new["Dhcp4"]["interfaces-config"]["interfaces"],
    )


def test_formatting_only_change_is_low_risk():
    impact = _run(lambda d: None)
    assert impact.unchanged and impact.risk == RISK_LOW and not impact.affected_leases


def test_adding_a_clean_reservation_is_low_risk():
    impact = _run(lambda d: d["subnet4"][0]["reservations"].append({"hostname": "nas", "hw-address": "aa:aa:aa:aa:aa:02", "ip-address": "192.0.2.60"}))
    assert impact.risk == RISK_LOW and not impact.unchanged
    assert [(v.name, v.before, v.after) for v in impact.reservation_changes] == [("nas", "", "aa:aa:aa:aa:aa:02 -> 192.0.2.60")]


def test_shrinking_a_pool_below_its_leases_is_high_risk():
    impact = _run(lambda d: d["subnet4"][0].update(pools=[{"pool": "192.0.2.108 - 192.0.2.109"}]))
    assert impact.risk == RISK_HIGH
    assert {a.ip for a in impact.affected_leases} == {"192.0.2.100", "192.0.2.101"}
    assert all("leaves the pool" in a.reason for a in impact.affected_leases)
    change = impact.subnet_changes[0]
    assert (change.capacity_before, change.capacity_after, change.active) == (10, 2, 2)
    assert not any("leased now" in w for w in impact.capacity_warnings)


def test_capacity_below_active_leases_is_reported():
    impact = _run(lambda d: d["subnet4"][0].update(pools=[{"pool": "192.0.2.100 - 192.0.2.100"}]))
    assert any("hold 1 addresses but 2 are leased" in w for w in impact.capacity_warnings)
    assert impact.risk == RISK_HIGH


def test_near_exhaustion_warns():
    impact = _run(lambda d: d["subnet4"][0].update(pools=[{"pool": "192.0.2.100 - 192.0.2.101"}]))
    assert any("close to exhaustion" in w for w in impact.capacity_warnings)


def test_removing_a_subnet_with_leases():
    impact = _run(lambda d: d["subnet4"].pop(1))
    assert impact.risk == RISK_HIGH
    assert impact.subnet_changes[0].kind == "removed"
    assert [a.ip for a in impact.affected_leases] == ["198.51.100.10"]
    assert "removed" in impact.affected_leases[0].reason


def test_reserving_a_leased_address_for_another_device():
    impact = _run(lambda d: d["subnet4"][0]["reservations"].append({"hostname": "cam", "hw-address": "aa:aa:aa:aa:aa:03", "ip-address": "192.0.2.100"}))
    assert [a.ip for a in impact.affected_leases] == ["192.0.2.100"]
    assert "aa:aa:aa:aa:aa:03" in impact.affected_leases[0].reason
    introduced = [f.finding for f in impact.introduced_findings]
    assert any(f.runtime and f.problem == "Reserved address leased to another device" for f in introduced)


def test_duplicate_global_reservation_is_an_introduced_critical_anomaly():
    def change(d):
        d["reservations"] = [{"hostname": "dup", "hw-address": "aa:aa:aa:aa:aa:09", "ip-address": "192.0.2.50"}]

    impact = _run(change)
    introduced = [f.finding for f in impact.introduced_findings]
    assert any(f.problem == "Duplicate reservation IP address" and not f.runtime for f in introduced)
    assert impact.risk == RISK_HIGH


def test_pre_existing_anomaly_is_not_introduced():
    def overlap(d):
        d["subnet4"][1]["pools"].append({"pool": "192.0.2.105 - 192.0.2.106"})

    base = copy.deepcopy(BASE)
    overlap(base["Dhcp4"])
    config = parse_kea_config(json.dumps(base))
    new = copy.deepcopy(base)
    new["Dhcp4"]["valid-lifetime"] = 7200
    impact = analyze(config, parse_kea_config(json.dumps(new)), LEASES, ["eth0"], ["eth0"])
    overlaps = [f for f in impact.findings if f.finding.problem == "Pool range overlaps another subnet"]
    assert len(overlaps) == 1 and not overlaps[0].introduced
    assert impact.risk == RISK_REVIEW


def test_option_and_interface_changes_need_review():
    def change(d):
        d["subnet4"][0]["option-data"][0]["data"] = "192.0.2.254"
        d["interfaces-config"]["interfaces"] = ["eth1"]

    impact = _run(change)
    assert impact.risk == RISK_REVIEW
    assert [(v.name, v.before, v.after) for v in impact.subnet_changes[0].settings] == [("routers", "192.0.2.1", "192.0.2.254")]
    assert impact.interface_change.after == "eth1"


def test_denying_a_client_affects_its_lease():
    def change(d):
        d["client-classes"] = [{"name": "DROP", "test": "pkt4.mac == 0xbbbbbbbbbb01"}]

    impact = _run(change)
    assert [a.ip for a in impact.affected_leases] == ["192.0.2.100"]
    assert "denied" in impact.affected_leases[0].reason


def test_summary_describes_effective_behavior():
    impact = _run(lambda d: None)
    assert "Listening on: eth0." in impact.summary
    assert any(line.startswith("192.0.2.0/24") and "192.0.2.100-192.0.2.109 (10 addresses, 2 in use)" in line and "router 192.0.2.1" in line for line in impact.summary)
    text = impact_as_text(impact)
    assert "Risk: low" in text and "Effective behavior" in text


def test_isc_configs_are_analyzed_the_same_way():
    old = parse("subnet 10.0.0.0 netmask 255.255.255.0 {\n  range 10.0.0.10 10.0.0.20;\n}\n")
    new = parse("subnet 10.0.0.0 netmask 255.255.255.0 {\n  range 10.0.0.15 10.0.0.20;\n}\n")
    impact = analyze(old, new, [_lease("10.0.0.10", "cc:cc:cc:cc:cc:01")], [], [])
    assert impact.risk == RISK_HIGH and [a.ip for a in impact.affected_leases] == ["10.0.0.10"]
