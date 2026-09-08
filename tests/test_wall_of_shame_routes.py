from datetime import datetime, timedelta

CONF = """
subnet 192.168.7.0 netmask 255.255.255.0 {
    range 192.168.7.10 192.168.7.50;
    host dev_res {
        hardware ethernet aa:aa:aa:aa:aa:01;
        fixed-address 192.168.7.11;
    }
}
"""


def _now():
    return datetime.now()


def _lease_block(ip: str, mac: str, state: str, starts) -> str:
    return f"lease {ip} {{\n  starts {starts.isoweekday() % 7} {starts.strftime('%Y/%m/%d %H:%M:%S')};\n  binding state {state};\n  hardware ethernet {mac};\n}}\n"


def _log_line(dt, message: str) -> str:
    return f"{dt.strftime('%b %d %H:%M:%S')} host dhcpd[1]: {message}\n"


def _seed_full(settings):
    now = _now()
    settings.dhcpd_conf_path.write_text(CONF)

    leases_text = (
        _lease_block("192.168.7.11", "aa:aa:aa:aa:aa:01", "active", now - timedelta(hours=1))
        + _lease_block("192.168.7.20", "cc:cc:cc:cc:cc:03", "free", now - timedelta(days=5))
        + _lease_block("192.168.7.21", "cc:cc:cc:cc:cc:03", "free", now - timedelta(hours=3))  # IP change
        + _lease_block("192.168.7.30", "dd:dd:dd:dd:dd:04", "abandoned", now - timedelta(hours=2))
    )
    settings.leases_path.write_text(leases_text)

    settings.dhcp_log_path.parent.mkdir(parents=True, exist_ok=True)
    log_text = (
        _log_line(now - timedelta(hours=1), "DHCPNAK on 192.168.7.11 to aa:aa:aa:aa:aa:01 via eth0")
        + _log_line(now - timedelta(hours=2), "DHCPNAK on 192.168.7.11 to aa:aa:aa:aa:aa:01 via eth0")
    )
    settings.dhcp_log_path.write_text(log_text)


def test_page_renders_with_time_range_links(admin_client, settings):
    _seed_full(settings)
    response = admin_client.get("/diagnostics/wall-of-shame")
    assert response.status_code == 200
    assert b"Wall of Shame" in response.content
    assert b"Last 24 hours" in response.content
    assert b"Last 7 days" in response.content
    assert b"All available" in response.content


def test_defaults_to_24h_window(admin_client, settings):
    _seed_full(settings)
    response = admin_client.get("/diagnostics/wall-of-shame")
    # Both seeded NAKs are within 1-2 hours, both should be counted by default.
    assert b">2<" in response.content


def test_nak_section_shows_offender(admin_client, settings):
    _seed_full(settings)
    response = admin_client.get("/diagnostics/wall-of-shame")
    assert b"aa:aa:aa:aa:aa:01" in response.content
    assert b"DHCPNAK offenders" in response.content


def test_nak_section_empty_state_when_out_of_window(admin_client, settings):
    _seed_full(settings)
    # NAKs are only 1-2 hours old; a 24h window still includes them, so
    # force an empty result by using a MAC-less log instead.
    settings.dhcp_log_path.write_text(_log_line(_now(), "DHCPDISCOVER from aa:aa:aa:aa:aa:01 via eth0"))
    response = admin_client.get("/diagnostics/wall-of-shame")
    assert b"No DHCP troublemakers found." in response.content


def test_nak_section_insufficient_data_when_log_missing(admin_client, settings):
    settings.dhcpd_conf_path.write_text(CONF)
    settings.leases_path.write_text("")
    # settings.dhcp_log_path deliberately left non-existent (conftest default).
    response = admin_client.get("/diagnostics/wall-of-shame")
    assert b"Not enough historical data available." in response.content


def test_ip_hoppers_section_shows_offender(admin_client, settings):
    _seed_full(settings)
    response = admin_client.get("/diagnostics/wall-of-shame?window=7d")
    assert b"IP hoppers" in response.content
    assert b"cc:cc:cc:cc:cc:03" in response.content


def test_ip_hoppers_insufficient_data_when_no_leases_file(admin_client, settings):
    settings.dhcpd_conf_path.write_text(CONF)
    response = admin_client.get("/diagnostics/wall-of-shame")
    assert b"Not enough historical data available." in response.content


def test_abandoned_section_shows_device_and_links_to_device_page(admin_client, settings):
    _seed_full(settings)
    response = admin_client.get("/diagnostics/wall-of-shame?window=7d")
    assert b"Abandoned leases" in response.content
    assert b"dd:dd:dd:dd:dd:04" in response.content
    assert b"/devices/dd%3Add%3Add%3Add%3Add%3A04" in response.content


def test_window_all_includes_older_entries_than_7d(admin_client, settings):
    now = _now()
    settings.dhcpd_conf_path.write_text(CONF)
    settings.leases_path.write_text(_lease_block("192.168.7.40", "ee:ee:ee:ee:ee:05", "abandoned", now - timedelta(days=30)))
    response_7d = admin_client.get("/diagnostics/wall-of-shame?window=7d")
    assert b"ee:ee:ee:ee:ee:05" not in response_7d.content
    response_all = admin_client.get("/diagnostics/wall-of-shame?window=all")
    assert b"ee:ee:ee:ee:ee:05" in response_all.content


def test_unknown_window_param_falls_back_to_default(admin_client, settings):
    _seed_full(settings)
    response = admin_client.get("/diagnostics/wall-of-shame?window=bogus")
    assert response.status_code == 200


def test_right_click_menu_reuses_existing_devices_menu(admin_client, settings):
    _seed_full(settings)
    response = admin_client.get("/diagnostics/wall-of-shame")
    assert b"openContextMenu(event, '/devices/aa%3Aaa%3Aaa%3Aaa%3Aaa%3A01/menu')" in response.content


def test_device_context_menu_route_still_works_for_wall_of_shame_devices(admin_client, settings):
    _seed_full(settings)
    response = admin_client.get("/devices/aa:aa:aa:aa:aa:01/menu")
    assert response.status_code == 200
    assert b"Open device" in response.content
    assert b"Diagnose device" in response.content


def test_viewer_can_view_wall_of_shame(viewer_client, settings):
    _seed_full(settings)
    assert viewer_client.get("/diagnostics/wall-of-shame").status_code == 200


def test_sidebar_shows_wall_of_shame_under_diagnostics(admin_client, settings):
    _seed_full(settings)
    response = admin_client.get("/diagnostics/wall-of-shame")
    assert b"Wall of Shame" in response.content
    assert b"/diagnostics/wall-of-shame" in response.content
    assert b'<details class="group" open>' in response.content


def test_diagnostics_overview_links_to_wall_of_shame(admin_client, settings):
    _seed_full(settings)
    response = admin_client.get("/diagnostics")
    assert b"/diagnostics/wall-of-shame" in response.content
