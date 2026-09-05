from sandia.dhcpd import DhcpdConfig, Host, Option, Parameter, parse, serialize
from sandia.dhcpd.extra_options import apply_extra_options, get_extra_options

MANAGED = {"hardware", "fixed-address", "host-name", "next-server", "filename"}


def _wrap(host: Host) -> str:
    return serialize(DhcpdConfig(nodes=[host]))


def test_get_extra_options_excludes_managed_fields():
    host = Host(
        name="printer",
        body=[
            Parameter("hardware", "ethernet 00:11:22:33:44:55"),
            Parameter("fixed-address", "192.168.1.50"),
            Parameter("ddns-hostname", '"printer"'),
        ],
    )
    extra = get_extra_options(host.body, MANAGED)
    assert extra == 'ddns-hostname "printer";'


def test_get_extra_options_empty_when_nothing_unmanaged():
    host = Host(name="printer", body=[Parameter("hardware", "ethernet 00:11:22:33:44:55")])
    assert get_extra_options(host.body, MANAGED) == ""


def test_apply_extra_options_adds_new_statements():
    body = [Parameter("hardware", "ethernet 00:11:22:33:44:55")]
    new_body = apply_extra_options(body, MANAGED, 'ddns-hostname "printer";\noption tftp-server-name "tftp.local";')

    host = Host(name="printer", body=new_body)
    reparsed = parse(_wrap(host))
    printer = reparsed.find_host("printer")
    assert printer.get("ddns-hostname") == '"printer"'

    tftp = next(n for n in printer.body if isinstance(n, Option) and n.name == "tftp-server-name")
    assert tftp.value == '"tftp.local"'


def test_apply_extra_options_removes_stale_unmanaged_fields():
    body = [Parameter("hardware", "ethernet 00:11:22:33:44:55"), Parameter("ddns-hostname", '"old"')]
    new_body = apply_extra_options(body, MANAGED, "")  # cleared the field
    assert get_extra_options(new_body, MANAGED) == ""
    assert any(isinstance(n, Parameter) and n.name == "hardware" for n in new_body)


def test_apply_extra_options_replaces_rather_than_duplicates():
    body = [Parameter("hardware", "ethernet 00:11:22:33:44:55"), Parameter("ddns-hostname", '"old"')]
    new_body = apply_extra_options(body, MANAGED, 'ddns-hostname "new";')
    matches = [n for n in new_body if isinstance(n, Parameter) and n.name == "ddns-hostname"]
    assert len(matches) == 1
    assert matches[0].value == '"new"'
