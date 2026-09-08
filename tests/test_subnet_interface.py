from sandia.dhcpd import DhcpdConfig, Subnet, parse, serialize
from sandia.dhcpd.subnet_interface import get_subnet_interface, set_subnet_interface


def test_get_returns_none_when_no_tag():
    subnet = Subnet(network="192.168.1.0", netmask="255.255.255.0", body=[])
    config = DhcpdConfig(nodes=[subnet])
    assert get_subnet_interface(config, subnet) is None


def test_set_then_get_round_trips():
    subnet = Subnet(network="192.168.1.0", netmask="255.255.255.0", body=[])
    config = DhcpdConfig(nodes=[subnet])

    set_subnet_interface(config, subnet, "eth2")
    assert get_subnet_interface(config, subnet) == "eth2"

    # Must survive a real serialize -> parse round trip as valid syntax.
    text = serialize(config)
    assert "# interface: eth2" in text
    reparsed = parse(text)
    reparsed_subnet = reparsed.find_subnet(subnet.key)
    assert get_subnet_interface(reparsed, reparsed_subnet) == "eth2"


def test_changing_interface_does_not_duplicate_comment():
    subnet = Subnet(network="192.168.1.0", netmask="255.255.255.0", body=[])
    config = DhcpdConfig(nodes=[subnet])

    set_subnet_interface(config, subnet, "eth0")
    set_subnet_interface(config, subnet, "eth1")

    assert get_subnet_interface(config, subnet) == "eth1"
    comment_count = sum(1 for n in config.nodes if getattr(n, "text", "").startswith("interface:"))
    assert comment_count == 1


def test_clearing_interface_removes_comment():
    subnet = Subnet(network="192.168.1.0", netmask="255.255.255.0", body=[])
    config = DhcpdConfig(nodes=[subnet])

    set_subnet_interface(config, subnet, "eth0")
    set_subnet_interface(config, subnet, "")

    assert get_subnet_interface(config, subnet) is None
    assert len(config.nodes) == 1


def test_unrelated_comment_before_subnet_is_not_mistaken_for_interface_tag():
    from sandia.dhcpd.ast import Comment

    subnet = Subnet(network="192.168.1.0", netmask="255.255.255.0", body=[])
    config = DhcpdConfig(nodes=[Comment("just a regular note"), subnet])
    assert get_subnet_interface(config, subnet) is None
