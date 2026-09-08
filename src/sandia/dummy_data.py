from .config import Settings

DUMMY_CONF = """\
authoritative;
default-lease-time 600;
max-lease-time 7200;
option domain-name "example.test";
option domain-name-servers 8.8.8.8, 1.1.1.1;

# interface: eth0
subnet 192.168.50.0 netmask 255.255.255.0 {
    range 192.168.50.100 192.168.50.200;
    option routers 192.168.50.1;
    option broadcast-address 192.168.50.255;

    host printer {
        hardware ethernet b8:27:eb:12:34:56;
        fixed-address 192.168.50.50;
    }

    host nas {
        hardware ethernet b0:4e:26:aa:bb:cc;
        fixed-address 192.168.50.51;
    }
}

# interface: eth1
subnet 10.0.5.0 netmask 255.255.255.0 {
    range 10.0.5.50 10.0.5.150;
    option routers 10.0.5.1;
}

host workstation1 {
    hardware ethernet ac:de:48:11:22:33;
    fixed-address 192.168.50.60;
}
"""

DUMMY_INTERFACES_CONF = """\
# Defaults for isc-dhcp-server (sourced by init script / systemd unit).
# This is dummy data - editing it here has no effect on any real service.

DHCPDv4_CONF=/etc/dhcp/dhcpd.conf
DHCPDv4_PID=/run/dhcp-server/dhcpd.pid

INTERFACESv4="eth0 eth1"
INTERFACESv6=""
"""

DUMMY_LEASES = """\
lease 192.168.50.50 {
  starts 3 2026/09/02 08:00:00;
  ends 3 2026/09/02 20:00:00;
  binding state active;
  hardware ethernet b8:27:eb:12:34:56;
  client-hostname "printer";
}
lease 192.168.50.101 {
  starts 3 2026/09/02 09:15:00;
  ends 3 2026/09/02 21:15:00;
  binding state active;
  hardware ethernet ac:de:48:22:33:44;
  client-hostname "johns-laptop";
}
lease 192.168.50.102 {
  starts 3 2026/09/02 07:00:00;
  ends 3 2026/09/02 07:30:00;
  binding state free;
  hardware ethernet 22:33:44:55:66:77;
}
lease 192.168.50.103 {
  starts 3 2026/09/02 10:00:00;
  ends 3 2026/09/02 22:00:00;
  binding state active;
  hardware ethernet 18:65:71:22:33:44;
  client-hostname "guest-phone";
}
lease 10.0.5.75 {
  starts 3 2026/09/02 06:00:00;
  ends 3 2026/09/02 18:00:00;
  binding state active;
  hardware ethernet 40:b4:cd:11:22:33;
  client-hostname "iot-sensor";
}
"""

DUMMY_DHCP_LOG = """\
Sep  2 08:00:00 sandia-demo dhcpd[1234]: DHCPDISCOVER from b8:27:eb:12:34:56 via eth0
Sep  2 08:00:00 sandia-demo dhcpd[1234]: DHCPOFFER on 192.168.50.50 to b8:27:eb:12:34:56 via eth0
Sep  2 08:00:00 sandia-demo dhcpd[1234]: DHCPREQUEST for 192.168.50.50 (192.168.50.1) from b8:27:eb:12:34:56 via eth0
Sep  2 08:00:00 sandia-demo dhcpd[1234]: DHCPACK on 192.168.50.50 to b8:27:eb:12:34:56 via eth0
Sep  2 09:15:00 sandia-demo dhcpd[1234]: DHCPDISCOVER from ac:de:48:22:33:44 via eth0
Sep  2 09:15:00 sandia-demo dhcpd[1234]: DHCPOFFER on 192.168.50.101 to ac:de:48:22:33:44 via eth0
Sep  2 09:15:00 sandia-demo dhcpd[1234]: DHCPREQUEST for 192.168.50.101 (192.168.50.1) from ac:de:48:22:33:44 via eth0
Sep  2 09:15:00 sandia-demo dhcpd[1234]: DHCPACK on 192.168.50.101 to ac:de:48:22:33:44 via eth0
Sep  2 10:00:00 sandia-demo dhcpd[1234]: DHCPDISCOVER from 18:65:71:22:33:44 via eth0
Sep  2 10:00:00 sandia-demo dhcpd[1234]: DHCPOFFER on 192.168.50.103 to 18:65:71:22:33:44 via eth0
Sep  2 10:00:00 sandia-demo dhcpd[1234]: DHCPREQUEST for 192.168.50.103 (192.168.50.1) from 18:65:71:22:33:44 via eth0
Sep  2 10:00:00 sandia-demo dhcpd[1234]: DHCPACK on 192.168.50.103 to 18:65:71:22:33:44 via eth0
Sep  2 11:05:12 sandia-demo dhcpd[1234]: DHCPREQUEST for 192.168.50.220 from aa:bb:cc:00:11:22 via eth0: unknown lease 192.168.50.220
Sep  2 11:05:12 sandia-demo dhcpd[1234]: DHCPNAK on 192.168.50.220 to aa:bb:cc:00:11:22 via eth0
Sep  2 11:05:13 sandia-demo dhcpd[1234]: DHCPDISCOVER from aa:bb:cc:00:11:22 via eth0
Sep  2 12:40:07 sandia-demo dhcpd[1234]: DHCPDISCOVER from de:ad:be:ef:00:01 via eth1: no free leases
"""


def seed_dummy_data(settings: Settings) -> None:
    """Write synthetic dhcpd.conf/leases files for exploring the UI without
    a real isc-dhcp-server. Only writes if the files don't already exist,
    so edits made through the UI in a prior run survive a restart."""
    settings.dhcpd_conf_path.parent.mkdir(parents=True, exist_ok=True)
    if not settings.dhcpd_conf_path.exists():
        settings.dhcpd_conf_path.write_text(DUMMY_CONF)

    settings.leases_path.parent.mkdir(parents=True, exist_ok=True)
    if not settings.leases_path.exists():
        settings.leases_path.write_text(DUMMY_LEASES)

    settings.interfaces_conf_path.parent.mkdir(parents=True, exist_ok=True)
    if not settings.interfaces_conf_path.exists():
        settings.interfaces_conf_path.write_text(DUMMY_INTERFACES_CONF)

    settings.dhcp_log_path.parent.mkdir(parents=True, exist_ok=True)
    if not settings.dhcp_log_path.exists():
        settings.dhcp_log_path.write_text(DUMMY_DHCP_LOG)
