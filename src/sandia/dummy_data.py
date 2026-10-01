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


# The same demo network for SANDIA_DHCP_BACKEND=kea.
DUMMY_KEA_CONF = """\
// Dummy data - editing it here has no effect on any real service.
{
"Dhcp4": {
    "interfaces-config": { "interfaces": [ "eth0", "eth1" ] },
    "lease-database": { "type": "memfile", "lfc-interval": 3600 },
    "valid-lifetime": 600,
    "max-valid-lifetime": 7200,
    "option-data": [
        { "name": "domain-name", "data": "example.test" },
        { "name": "domain-name-servers", "data": "8.8.8.8, 1.1.1.1" }
    ],
    "subnet4": [
        {
            "id": 1,
            "subnet": "192.168.50.0/24",
            "pools": [ { "pool": "192.168.50.100 - 192.168.50.200" } ],
            "option-data": [ { "name": "routers", "data": "192.168.50.1" } ],
            "reservations": [
                { "hostname": "printer", "hw-address": "b8:27:eb:12:34:56", "ip-address": "192.168.50.50" },
                { "hostname": "nas", "hw-address": "b0:4e:26:aa:bb:cc", "ip-address": "192.168.50.51" },
                { "hostname": "workstation1", "hw-address": "ac:de:48:11:22:33", "ip-address": "192.168.50.60" }
            ]
        },
        {
            "id": 2,
            "subnet": "10.0.5.0/24",
            "pools": [ { "pool": "10.0.5.50 - 10.0.5.150" } ],
            "option-data": [ { "name": "routers", "data": "10.0.5.1" } ]
        }
    ]
}
}
"""

DUMMY_KEA_LEASES = """\
address,hwaddr,client_id,valid_lifetime,expire,subnet_id,fqdn_fwd,fqdn_rev,hostname,state,user_context,pool_id
192.168.50.50,b8:27:eb:12:34:56,,43200,1788379200,1,0,0,printer,0,,0
192.168.50.101,ac:de:48:22:33:44,,43200,1788383700,1,0,0,johns-laptop,0,,0
192.168.50.102,22:33:44:55:66:77,,1800,1788334200,1,0,0,,2,,0
192.168.50.103,18:65:71:22:33:44,,43200,1788386400,1,0,0,guest-phone,0,,0
10.0.5.75,40:b4:cd:11:22:33,,43200,1788372000,2,0,0,iot-sensor,0,,0
"""

DUMMY_KEA_LOG = """\
2026-09-02 08:00:00.101 INFO  [kea-dhcp4.leases/812.140] DHCP4_LEASE_OFFER [hwtype=1 b8:27:eb:12:34:56], cid=[no info], tid=0x1a2b3c01: lease 192.168.50.50 will be offered
2026-09-02 08:00:00.212 INFO  [kea-dhcp4.leases/812.140] DHCP4_LEASE_ALLOC [hwtype=1 b8:27:eb:12:34:56], cid=[no info], tid=0x1a2b3c01: lease 192.168.50.50 has been allocated for 43200 seconds
2026-09-02 09:15:00.101 INFO  [kea-dhcp4.leases/812.140] DHCP4_LEASE_OFFER [hwtype=1 ac:de:48:22:33:44], cid=[no info], tid=0x1a2b3c02: lease 192.168.50.101 will be offered
2026-09-02 09:15:00.212 INFO  [kea-dhcp4.leases/812.140] DHCP4_LEASE_ALLOC [hwtype=1 ac:de:48:22:33:44], cid=[no info], tid=0x1a2b3c02: lease 192.168.50.101 has been allocated for 43200 seconds
2026-09-02 10:00:00.101 INFO  [kea-dhcp4.leases/812.140] DHCP4_LEASE_OFFER [hwtype=1 18:65:71:22:33:44], cid=[no info], tid=0x1a2b3c03: lease 192.168.50.103 will be offered
2026-09-02 10:00:00.212 INFO  [kea-dhcp4.leases/812.140] DHCP4_LEASE_ALLOC [hwtype=1 18:65:71:22:33:44], cid=[no info], tid=0x1a2b3c03: lease 192.168.50.103 has been allocated for 43200 seconds
2026-09-02 11:05:12.300 DEBUG [kea-dhcp4.bad-packets/812.140] DHCP4_PACKET_NAK_0004 [hwtype=1 aa:bb:cc:00:11:22], cid=[no info], tid=0x1a2b3c04: failed to grant a lease, client sent ciaddr 0.0.0.0, requested-ip-address 192.168.50.220
2026-09-02 12:40:07.400 WARN  [kea-dhcp4.alloc-engine/812.140] ALLOC_ENGINE_V4_ALLOC_FAIL_SUBNET [hwtype=1 de:ad:be:ef:00:01], cid=[no info], tid=0x1a2b3c05: failed to allocate an IPv4 lease in the subnet 10.0.5.0/24, subnet-id 2, shared network (none)
"""


def seed_dummy_data(settings: Settings) -> None:
    """Write synthetic config/leases files for exploring the UI without a
    real DHCP server. Only writes if the files don't already exist, so
    edits made through the UI in a prior run survive a restart."""
    kea = settings.dhcp_backend == "kea"
    settings.dhcpd_conf_path.parent.mkdir(parents=True, exist_ok=True)
    if not settings.dhcpd_conf_path.exists():
        settings.dhcpd_conf_path.write_text(DUMMY_KEA_CONF if kea else DUMMY_CONF)

    settings.leases_path.parent.mkdir(parents=True, exist_ok=True)
    if not settings.leases_path.exists():
        settings.leases_path.write_text(DUMMY_KEA_LEASES if kea else DUMMY_LEASES)

    if not kea:
        settings.interfaces_conf_path.parent.mkdir(parents=True, exist_ok=True)
        if not settings.interfaces_conf_path.exists():
            settings.interfaces_conf_path.write_text(DUMMY_INTERFACES_CONF)

    settings.dhcp_log_path.parent.mkdir(parents=True, exist_ok=True)
    if not settings.dhcp_log_path.exists():
        settings.dhcp_log_path.write_text(DUMMY_KEA_LOG if kea else DUMMY_DHCP_LOG)
