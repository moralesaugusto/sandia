CONF = """
subnet 192.168.9.0 netmask 255.255.255.0 {
    range 192.168.9.10 192.168.9.20;
    host dev_res {
        hardware ethernet aa:aa:aa:aa:aa:01;
        fixed-address 192.168.9.10;
    }
}
host deny-bbbbbbbbbb02 {
    hardware ethernet bb:bb:bb:bb:bb:02;
    deny booting;
}
"""

LEASES = """
lease 192.168.9.10 {
  starts 3 2026/09/02 08:00:00;
  ends 3 2026/09/02 20:00:00;
  binding state active;
  hardware ethernet aa:aa:aa:aa:aa:01;
  client-hostname "res-device";
}
lease 192.168.9.11 {
  starts 3 2026/09/02 09:00:00;
  ends 3 2026/09/02 21:00:00;
  binding state active;
  hardware ethernet cc:cc:cc:cc:cc:03;
  client-hostname "dyn-device";
}
lease 192.168.9.12 {
  starts 3 2026/09/02 07:00:00;
  ends 3 2026/09/02 19:00:00;
  binding state active;
  hardware ethernet bb:bb:bb:bb:bb:02;
}
"""

DHCP_LOG = (
    "Sep  2 09:00:00 host dhcpd[1]: DHCPDISCOVER from cc:cc:cc:cc:cc:03 via eth0\n"
    "Sep  2 09:00:00 host dhcpd[1]: DHCPOFFER on 192.168.9.11 to cc:cc:cc:cc:cc:03 via eth0\n"
    "Sep  2 09:00:01 host dhcpd[1]: DHCPACK on 192.168.9.11 to cc:cc:cc:cc:cc:03 via eth0\n"
    "Sep  2 10:00:00 host dhcpd[1]: DHCPNAK on 192.168.9.99 to dd:dd:dd:dd:dd:04 via eth0: unknown lease\n"
)


def _seed(settings):
    settings.dhcpd_conf_path.write_text(CONF)
    settings.leases_path.write_text(LEASES)
    settings.dhcp_log_path.parent.mkdir(parents=True, exist_ok=True)
    settings.dhcp_log_path.write_text(DHCP_LOG)


def test_devices_page_lists_all_discovered_devices(admin_client, settings):
    _seed(settings)
    response = admin_client.get("/devices")
    assert response.status_code == 200
    assert b"aa:aa:aa:aa:aa:01" in response.content
    assert b"cc:cc:cc:cc:cc:03" in response.content
    assert b"bb:bb:bb:bb:bb:02" in response.content


def test_devices_page_viewer_can_access(viewer_client, settings):
    _seed(settings)
    assert viewer_client.get("/devices").status_code == 200


def test_devices_table_partial_used_by_htmx(admin_client, settings):
    _seed(settings)
    response = admin_client.get("/devices/table")
    assert response.status_code == 200
    assert b"<table" in response.content


def test_filter_by_status_problem(admin_client, settings):
    _seed(settings)
    response = admin_client.get("/devices/table", params={"status": "problem"})
    assert b"bb:bb:bb:bb:bb:02" in response.content
    assert b"aa:aa:aa:aa:aa:01" not in response.content


def test_filter_by_reservation_yes(admin_client, settings):
    _seed(settings)
    response = admin_client.get("/devices/table", params={"reservation": "yes"})
    assert b"aa:aa:aa:aa:aa:01" in response.content
    assert b"cc:cc:cc:cc:cc:03" not in response.content


def test_search_by_mac(admin_client, settings):
    _seed(settings)
    response = admin_client.get("/devices/table", params={"q": "cc:cc:cc:cc:cc:03"})
    assert b"cc:cc:cc:cc:cc:03" in response.content
    assert b"aa:aa:aa:aa:aa:01" not in response.content


def test_search_by_ip(admin_client, settings):
    _seed(settings)
    response = admin_client.get("/devices/table", params={"q": "192.168.9.10"})
    assert b"aa:aa:aa:aa:aa:01" in response.content
    assert b"cc:cc:cc:cc:cc:03" not in response.content


def test_export_csv_headers_and_content(admin_client, settings):
    _seed(settings)
    response = admin_client.get("/devices/export.csv")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    body = response.content.decode()
    assert "mac,hostname,vendor" in body
    assert "aa:aa:aa:aa:aa:01" in body


def test_device_menu_reserved_device_offers_edit_not_lease(admin_client, settings):
    _seed(settings)
    response = admin_client.get("/devices/aa:aa:aa:aa:aa:01/menu")
    assert response.status_code == 200
    assert b"Edit reservation" in response.content
    assert b"Lease IP" not in response.content


def test_device_menu_unreserved_device_offers_lease_ip(admin_client, settings):
    _seed(settings)
    response = admin_client.get("/devices/cc:cc:cc:cc:cc:03/menu")
    assert response.status_code == 200
    assert b"Lease IP" in response.content
    assert b"Deny this client" in response.content


def test_device_menu_denied_device_shows_denial_indicator(admin_client, settings):
    _seed(settings)
    response = admin_client.get("/devices/bb:bb:bb:bb:bb:02/menu")
    assert response.status_code == 200
    assert b"Client is denied" in response.content


def test_device_menu_viewer_hides_mutating_actions(viewer_client, settings):
    _seed(settings)
    response = viewer_client.get("/devices/cc:cc:cc:cc:cc:03/menu")
    assert response.status_code == 200
    assert b"Lease IP" not in response.content
    assert b"Deny this client" not in response.content
    assert b"Open device" in response.content
    assert b"Diagnose device" in response.content


def test_device_menu_unknown_mac(admin_client, settings):
    _seed(settings)
    response = admin_client.get("/devices/ff:ff:ff:ff:ff:ff/menu")
    assert response.status_code == 200
    assert b"Device not found" in response.content


def test_device_menu_delete_actions_confirm_before_submitting(admin_client, settings):
    _seed(settings)
    response = admin_client.get("/devices/aa:aa:aa:aa:aa:01/menu")
    assert b"onsubmit=\"return confirm(" in response.content


def test_device_detail_page_shows_identity_and_network_state(admin_client, settings):
    _seed(settings)
    response = admin_client.get("/devices/aa:aa:aa:aa:aa:01")
    assert response.status_code == 200
    assert b"res-device" in response.content or b"res_a" in response.content
    assert b"192.168.9.10" in response.content
    assert b"192.168.9.0/255.255.255.0" in response.content


def test_device_detail_shows_dhcp_activity(admin_client, settings):
    _seed(settings)
    response = admin_client.get("/devices/cc:cc:cc:cc:cc:03")
    assert response.status_code == 200
    assert b"DHCPDISCOVER" in response.content
    assert b"DHCPACK" in response.content


def test_device_detail_shows_diagnostics_summary_and_link(admin_client, settings):
    _seed(settings)
    response = admin_client.get("/devices/bb:bb:bb:bb:bb:02")
    assert response.status_code == 200
    assert b"Diagnostics" in response.content
    assert b"/diagnostics/client?mac=bb%3Abb%3Abb%3Abb%3Abb%3A02" in response.content


def test_device_detail_unknown_mac_redirects(admin_client, settings):
    _seed(settings)
    response = admin_client.get("/devices/ff:ff:ff:ff:ff:ff")
    assert response.status_code == 303
    assert response.headers["location"] == "/devices"


def test_device_to_ip_navigation_links_to_subnet_map(admin_client, settings):
    _seed(settings)
    response = admin_client.get("/devices/aa:aa:aa:aa:aa:01")
    assert b"/subnets/192.168.9.0_255.255.255.0/map" in response.content


def test_ip_to_device_navigation_from_subnet_map_menu(admin_client, settings):
    _seed(settings)
    response = admin_client.get("/subnets/192.168.9.0_255.255.255.0/map/192.168.9.10/menu")
    assert response.status_code == 200
    assert b"/devices/aa%3Aaa%3Aaa%3Aaa%3Aaa%3A01" in response.content


def test_ip_to_device_navigation_from_lease_menu(admin_client, settings):
    _seed(settings)
    response = admin_client.get("/leases/192.168.9.11/menu")
    assert response.status_code == 200
    assert b"/devices/cc%3Acc%3Acc%3Acc%3Acc%3A03" in response.content


def test_device_navigation_from_reservations_menu(admin_client, settings):
    _seed(settings)
    response = admin_client.get("/reservations/dev_res/menu")
    assert response.status_code == 200
    assert b"/devices/aa%3Aaa%3Aaa%3Aaa%3Aaa%3A01" in response.content


def test_lease_form_shows_suggestion_for_unreserved_device(operator_client, settings):
    _seed(settings)
    response = operator_client.get("/devices/cc:cc:cc:cc:cc:03/lease")
    assert response.status_code == 200
    assert b"192.168.9." in response.content


def test_lease_form_redirects_to_edit_when_already_reserved(operator_client, settings):
    _seed(settings)
    response = operator_client.get("/devices/aa:aa:aa:aa:aa:01/lease")
    assert response.status_code == 303
    assert response.headers["location"] == "/reservations/dev_res/edit"


def test_lease_form_requires_operator(viewer_client, settings):
    _seed(settings)
    response = viewer_client.get("/devices/cc:cc:cc:cc:cc:03/lease")
    assert response.status_code == 403


def test_lease_form_continue_link_prefills_reservation_form(operator_client, settings):
    _seed(settings)
    response = operator_client.get("/devices/cc:cc:cc:cc:cc:03/lease")
    assert b"/reservations/new?mac=cc" in response.content


def test_delete_lease_removes_record_and_backs_up(operator_client, settings):
    _seed(settings)
    response = operator_client.post("/devices/cc:cc:cc:cc:cc:03/delete-lease")
    assert response.status_code == 303

    updated = settings.leases_path.read_text()
    assert "192.168.9.11" not in updated
    backups = list(settings.backup_dir.glob("dhcpd.leases.*"))
    assert len(backups) == 1


def test_delete_lease_requires_operator(viewer_client, settings):
    _seed(settings)
    response = viewer_client.post("/devices/cc:cc:cc:cc:cc:03/delete-lease")
    assert response.status_code == 403
    assert "192.168.9.11" in settings.leases_path.read_text()


def test_delete_lease_device_with_no_lease_at_all(operator_client, settings):
    settings.dhcpd_conf_path.write_text(
        'host reserved_only {\n  hardware ethernet 99:99:99:99:99:99;\n  fixed-address 192.168.9.99;\n}\n'
    )
    settings.leases_path.write_text("")
    response = operator_client.post("/devices/99:99:99:99:99:99/delete-lease")
    assert response.status_code == 303


def test_bulk_delete_lease_records(operator_client, settings):
    _seed(settings)
    response = operator_client.post("/devices/bulk-delete-lease", data={"macs": ["cc:cc:cc:cc:cc:03", "bb:bb:bb:bb:bb:02"]})
    assert response.status_code == 303

    updated = settings.leases_path.read_text()
    assert "192.168.9.11" not in updated
    assert "192.168.9.12" not in updated
    assert "192.168.9.10" in updated  # untouched


def test_bulk_delete_lease_requires_operator(viewer_client, settings):
    _seed(settings)
    response = viewer_client.post("/devices/bulk-delete-lease", data={"macs": ["cc:cc:cc:cc:cc:03"]})
    assert response.status_code == 403


def test_bulk_delete_lease_no_selection_is_a_clean_error(operator_client, settings):
    _seed(settings)
    response = operator_client.post("/devices/bulk-delete-lease", data={})
    assert response.status_code == 303


def test_devices_list_bulk_delete_confirms_before_submitting(admin_client, settings):
    _seed(settings)
    response = admin_client.get("/devices")
    assert b"onclick=\"return confirm(" in response.content


def test_devices_list_hides_bulk_controls_from_viewer(viewer_client, settings):
    _seed(settings)
    response = viewer_client.get("/devices")
    assert b'name="macs"' not in response.content


def test_global_search_offers_device_search_link(admin_client, settings):
    _seed(settings)
    response = admin_client.get("/search/suggest", params={"q": "cc:cc:cc:cc:cc:03"})
    assert response.status_code == 200
    assert b"/devices?q=cc" in response.content


def test_dashboard_shows_device_counts(admin_client, settings):
    _seed(settings)
    response = admin_client.get("/")
    assert response.status_code == 200
    assert b"Devices" in response.content
    assert b"Device problems" in response.content
    assert b"/devices?status=problem" in response.content
