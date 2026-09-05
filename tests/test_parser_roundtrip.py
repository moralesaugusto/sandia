from pathlib import Path

from sandia.dhcpd import Host, Parameter, Subnet, UnknownBlock, parse, serialize

FIXTURE = Path(__file__).parent / "fixtures" / "sample_dhcpd.conf"


def test_parses_structure():
    config = parse(FIXTURE.read_text())

    assert config.get("default-lease-time") == "600"
    assert config.get("max-lease-time") == "7200"

    subnets = config.subnets
    assert len(subnets) == 1
    assert subnets[0].network == "192.168.1.0"
    assert subnets[0].netmask == "255.255.255.0"
    assert subnets[0].get("routers") == "192.168.1.1"
    assert subnets[0].get("range") == "192.168.1.100 192.168.1.200"
    assert any(isinstance(n, UnknownBlock) and n.header.startswith("shared-network") for n in config.nodes)

    hosts = config.all_hosts
    names = {h.name for h in hosts}
    assert names == {"printer", "server1", "laptop"}

    printer = config.find_host("printer")
    assert printer.fixed_address == "192.168.1.50"
    assert printer.mac == "00:11:22:33:44:55"


def test_roundtrip_is_idempotent():
    text = FIXTURE.read_text()
    config1 = parse(text)
    serialized = serialize(config1)
    config2 = parse(serialized)

    assert config1 == config2


def test_roundtrip_preserves_unknown_block_content():
    text = FIXTURE.read_text()
    config = parse(text)
    unknown = next(n for n in config.nodes if isinstance(n, UnknownBlock))
    assert "range 10.0.0.100 10.0.0.200;" in unknown.raw_body

    serialized = serialize(config)
    assert "shared-network office" in serialized
    assert "range 10.0.0.100 10.0.0.200;" in serialized


def test_mutation_and_reserialize():
    config = parse(FIXTURE.read_text())
    subnet = config.subnets[0]
    subnet.body.append(
        Host(
            name="newclient",
            body=[
                Parameter("hardware", "ethernet de:ad:be:ef:00:01"),
                Parameter("fixed-address", "192.168.1.60"),
            ],
        )
    )
    serialized = serialize(config)
    reparsed = parse(serialized)
    assert reparsed.find_host("newclient").fixed_address == "192.168.1.60"


def test_add_and_remove_subnet():
    config = parse(FIXTURE.read_text())
    config.nodes.append(Subnet(network="10.10.10.0", netmask="255.255.255.0", body=[]))
    assert config.find_subnet("10.10.10.0_255.255.255.0") is not None
    assert config.remove_subnet("10.10.10.0_255.255.255.0")
    assert config.find_subnet("10.10.10.0_255.255.255.0") is None
