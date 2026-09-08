def test_diagnostics_home_lists_subnets(admin_client):
    response = admin_client.get("/diagnostics")
    assert response.status_code == 200
    assert b"192.168.1.0/255.255.255.0" in response.content


def test_diagnostics_home_accessible_to_viewer(viewer_client):
    assert viewer_client.get("/diagnostics").status_code == 200


def test_server_diagnostics_page_renders(admin_client):
    response = admin_client.get("/diagnostics/server")
    assert response.status_code == 200
    assert b"Server diagnostics" in response.content


def test_server_diagnostics_flags_missing_dhcp_log(admin_client):
    # conftest's settings fixture points dhcp_log_path at a file that
    # doesn't exist, so this should surface as an explicit gap, not silence.
    response = admin_client.get("/diagnostics/server")
    assert b"DHCP log not available" in response.content


def test_client_diagnostics_healthy_for_active_reserved_client(admin_client):
    # fixture: "printer" reservation (mac 00:11:22:33:44:55) has an active lease at 192.168.1.50
    response = admin_client.get("/diagnostics/client", params={"mac": "00:11:22:33:44:55"})
    assert response.status_code == 200
    assert b">healthy<" in response.content
    assert b"valid, active lease" in response.content


def test_client_diagnostics_with_no_identifiers_is_unknown(admin_client):
    response = admin_client.get("/diagnostics/client")
    assert response.status_code == 200
    assert b">unknown<" in response.content
    assert b"Insufficient evidence" in response.content


def test_client_diagnostics_shows_flow_steps(admin_client):
    response = admin_client.get("/diagnostics/client", params={"mac": "00:11:22:33:44:55"})
    assert b"DHCP flow" in response.content
    assert b"Reservation lookup" in response.content


def test_subnet_diagnostics_page_renders(admin_client):
    response = admin_client.get("/subnets/192.168.1.0_255.255.255.0/diagnose")
    assert response.status_code == 200
    assert b"Subnet 192.168.1.0/255.255.255.0" in response.content


def test_subnet_diagnostics_unknown_subnet_redirects(admin_client):
    response = admin_client.get("/subnets/does-not-exist/diagnose")
    assert response.status_code == 303
    assert response.headers["location"] == "/subnets"


def test_subnet_diagnostics_viewer_can_access(viewer_client):
    assert viewer_client.get("/subnets/192.168.1.0_255.255.255.0/diagnose").status_code == 200


def test_lease_menu_offers_diagnose_client_link(admin_client):
    response = admin_client.get("/leases/192.168.1.50/menu")
    assert response.status_code == 200
    assert b"Diagnose device" in response.content
    assert b"/diagnostics/client?mac=00%3A11%3A22%3A33%3A44%3A55" in response.content


def test_lease_menu_diagnose_link_visible_to_viewer(viewer_client):
    response = viewer_client.get("/leases/192.168.1.50/menu")
    assert b"Diagnose device" in response.content


def test_reservation_menu_offers_diagnose_link(admin_client):
    response = admin_client.get("/reservations/printer/menu")
    assert response.status_code == 200
    assert b"Diagnose reservation" in response.content
    assert b"/reservations/printer/edit" in response.content


def test_reservation_menu_hides_edit_for_viewer(viewer_client):
    response = viewer_client.get("/reservations/printer/menu")
    assert response.status_code == 200
    assert b"Diagnose reservation" in response.content
    assert b"/reservations/printer/edit" not in response.content


def test_reservation_menu_not_found(admin_client):
    response = admin_client.get("/reservations/does-not-exist/menu")
    assert response.status_code == 200
    assert b"Reservation not found" in response.content


def test_reservations_list_wires_context_menu(admin_client):
    response = admin_client.get("/reservations")
    assert response.status_code == 200
    assert b"openContextMenu(event, '/reservations/printer/menu')" in response.content


def test_subnets_list_offers_diagnose_link(admin_client):
    response = admin_client.get("/subnets")
    assert response.status_code == 200
    assert b"/subnets/192.168.1.0_255.255.255.0/diagnose" in response.content


def test_service_page_offers_diagnose_link(admin_client):
    response = admin_client.get("/service")
    assert response.status_code == 200
    assert b"/diagnostics/server" in response.content
