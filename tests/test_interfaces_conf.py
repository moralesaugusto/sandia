from sandia.interfaces_conf import get_interfaces, set_interfaces

SAMPLE = """\
# Defaults for isc-dhcp-server (sourced by /etc/init.d/isc-dhcp-server)

#DHCPDv4_CONF=/etc/dhcp/dhcpd.conf
#DHCPDv4_PID=/var/run/dhcpd.pid

# Additional options to start dhcpd with.
OPTIONS=""

# On what interfaces should the DHCP server (dhcpd) serve DHCP requests?
INTERFACESv4="eth0 eth1"
INTERFACESv6=""
"""


def test_get_interfaces_parses_quoted_list():
    assert get_interfaces(SAMPLE) == ["eth0", "eth1"]


def test_get_interfaces_empty_when_absent():
    assert get_interfaces("") == []
    assert get_interfaces("SOME_OTHER_VAR=1\n") == []


def test_get_interfaces_empty_string_value():
    assert get_interfaces('INTERFACESv4=""\n') == []


def test_set_interfaces_replaces_existing_line_only():
    updated = set_interfaces(SAMPLE, ["eth2"])
    assert 'INTERFACESv4="eth2"' in updated
    assert get_interfaces(updated) == ["eth2"]
    # everything else untouched
    assert "#DHCPDv4_CONF=/etc/dhcp/dhcpd.conf" in updated
    assert 'INTERFACESv6=""' in updated
    assert updated.count("INTERFACESv4=") == 1


def test_set_interfaces_joins_multiple_names():
    updated = set_interfaces(SAMPLE, ["eth1", "eth2", "eth3"])
    assert get_interfaces(updated) == ["eth1", "eth2", "eth3"]


def test_set_interfaces_clears_to_empty():
    updated = set_interfaces(SAMPLE, [])
    assert 'INTERFACESv4=""' in updated
    assert get_interfaces(updated) == []


def test_set_interfaces_appends_when_line_absent():
    updated = set_interfaces("SOME_OTHER_VAR=1\n", ["eth0"])
    assert "SOME_OTHER_VAR=1" in updated
    assert get_interfaces(updated) == ["eth0"]


def test_set_interfaces_on_commented_out_line_uncomments_it():
    text = '#INTERFACESv4=""\n'
    updated = set_interfaces(text, ["eth0"])
    assert get_interfaces(updated) == ["eth0"]
    assert "#INTERFACESv4" not in updated


def test_round_trip_idempotent():
    once = set_interfaces(SAMPLE, ["eth5"])
    twice = set_interfaces(once, ["eth5"])
    assert once == twice
