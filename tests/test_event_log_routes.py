LOG = """\
Sep  2 08:00:00 host dhcpd[1]: DHCPDISCOVER from aa:aa:aa:aa:aa:01 via eth0
Sep  2 08:00:01 host dhcpd[1]: DHCPACK on 192.168.1.101 to aa:aa:aa:aa:aa:01 (laptop) via eth0
Sep  2 09:00:00 host dhcpd[1]: DHCPNAK on 192.168.1.220 to bb:bb:bb:bb:bb:02 via eth0: lease in use
Sep  2 09:30:00 host dhcpd[1]: Internet Systems Consortium DHCP Server 4.4.3
"""


def _write_log(settings, text=LOG):
    settings.dhcp_log_path.parent.mkdir(parents=True, exist_ok=True)
    settings.dhcp_log_path.write_text(text)


def test_page_lists_events_newest_first(viewer_client, settings):
    _write_log(settings)
    body = viewer_client.get("/diagnostics/events").text

    assert "DHCP Event Log" in body
    assert "4 matching events." in body
    assert body.index("Internet Systems Consortium") < body.index("DHCPNAK</span>") < body.index("DHCPDISCOVER</span>")


def test_kind_filter(viewer_client, settings):
    _write_log(settings)
    body = viewer_client.get("/diagnostics/events/table?kind=DHCPNAK").text

    assert "1 matching event." in body
    assert "192.168.1.220" in body
    assert "lease in use" in body
    assert "192.168.1.101" not in body


def test_search_matches_hostname_and_mac(viewer_client, settings):
    _write_log(settings)

    by_hostname = viewer_client.get("/diagnostics/events/table?q=LAPTOP").text
    assert "1 matching event." in by_hostname
    assert "192.168.1.101" in by_hostname

    by_mac = viewer_client.get("/diagnostics/events/table?q=aa:aa:aa:aa:aa:01").text
    assert "2 matching events." in by_mac


def test_rows_with_a_mac_open_the_device_context_menu(viewer_client, settings):
    _write_log(settings)
    body = viewer_client.get("/diagnostics/events/table?kind=DHCPNAK").text

    assert "openContextMenu(event, '/devices/bb%3Abb%3Abb%3Abb%3Abb%3A02/menu')" in body


def test_row_cap_shows_newest(viewer_client, settings, monkeypatch):
    from sandia.routers import diagnostics

    monkeypatch.setattr(diagnostics, "MAX_EVENT_ROWS", 2)
    _write_log(settings)
    body = viewer_client.get("/diagnostics/events/table").text

    assert "Showing the newest 2 of 4 matching events." in body
    assert "DHCPNAK" in body
    assert "DHCPDISCOVER" not in body


def test_missing_log_shows_reason(viewer_client, settings):
    body = viewer_client.get("/diagnostics/events").text

    assert f"DHCP log not found at {settings.dhcp_log_path}" in body


def test_requires_login(client):
    response = client.get("/diagnostics/events")
    assert response.status_code == 303
    assert response.headers["location"] == "/login"
