CONF = """
subnet 192.168.9.0 netmask 255.255.255.0 {
    range 192.168.9.10 192.168.9.15;
    host res10 {
        hardware ethernet aa:aa:aa:aa:aa:01;
        fixed-address 192.168.9.10;
    }
    host res11 {
        hardware ethernet aa:aa:aa:aa:aa:02;
        fixed-address 192.168.9.11;
    }
}
host deny-aaaaaaaaaa04 {
    hardware ethernet aa:aa:aa:aa:aa:04;
    deny booting;
}
"""

LEASES = """
lease 192.168.9.11 {
  binding state active;
  hardware ethernet aa:aa:aa:aa:aa:02;
}
lease 192.168.9.12 {
  binding state active;
  hardware ethernet aa:aa:aa:aa:aa:03;
}
lease 192.168.9.13 {
  binding state active;
  hardware ethernet aa:aa:aa:aa:aa:04;
}
"""

MAP_URL = "/subnets/192.168.9.0_255.255.255.0/map"


def _seed(settings):
    settings.dhcpd_conf_path.write_text(CONF)
    settings.leases_path.write_text(LEASES)


def test_map_page_renders_utilization_summary(admin_client, settings):
    _seed(settings)
    response = admin_client.get(MAP_URL)
    assert response.status_code == 200
    assert b"4 / 6 used" in response.content


def test_map_page_lists_reservations_outside_pool_range(admin_client, settings):
    # the shared fixture's "printer" reservation (192.168.1.50) sits outside its subnet's 100-200 range.
    response = admin_client.get("/subnets/192.168.1.0_255.255.255.0/map")
    assert response.status_code == 200
    assert b"Reservations outside the pool range" in response.content
    assert b"printer" in response.content
    assert b"/reservations/printer/edit" in response.content


def test_map_page_unknown_subnet_redirects(admin_client):
    response = admin_client.get("/subnets/does-not-exist/map")
    assert response.status_code == 303
    assert response.headers["location"] == "/subnets"


def test_map_viewer_can_view(viewer_client, settings):
    _seed(settings)
    assert viewer_client.get(MAP_URL).status_code == 200


def test_menu_free_cell_offers_reserve_for_operator(operator_client, settings):
    _seed(settings)
    response = operator_client.get(f"{MAP_URL}/192.168.9.14/menu")
    assert response.status_code == 200
    assert b"Reserve this IP" in response.content


def test_menu_free_cell_hides_reserve_for_viewer(viewer_client, settings):
    _seed(settings)
    response = viewer_client.get(f"{MAP_URL}/192.168.9.14/menu")
    assert response.status_code == 200
    assert b"Reserve this IP" not in response.content
    assert b"Copy IP address" in response.content


def test_menu_reserved_cell_links_to_edit(admin_client, settings):
    _seed(settings)
    response = admin_client.get(f"{MAP_URL}/192.168.9.10/menu")
    assert response.status_code == 200
    assert b'Edit reservation "res10"' in response.content
    assert b"/reservations/res10/edit" in response.content


def test_menu_reserved_online_cell_links_to_edit(admin_client, settings):
    _seed(settings)
    response = admin_client.get(f"{MAP_URL}/192.168.9.11/menu")
    assert response.status_code == 200
    assert b'Edit reservation "res11"' in response.content


def test_menu_leased_cell_offers_reserve_and_deny(operator_client, settings):
    _seed(settings)
    response = operator_client.get(f"{MAP_URL}/192.168.9.12/menu")
    assert response.status_code == 200
    assert b"Reserve this lease" in response.content
    assert b"Deny this client" in response.content


def test_menu_leased_cell_hides_actions_for_viewer(viewer_client, settings):
    _seed(settings)
    response = viewer_client.get(f"{MAP_URL}/192.168.9.12/menu")
    assert response.status_code == 200
    assert b"Reserve this lease" not in response.content
    assert b"Deny this client" not in response.content
    assert b"Copy MAC address" in response.content


def test_menu_denied_cell_shows_denial_and_edit_link(admin_client, settings):
    _seed(settings)
    response = admin_client.get(f"{MAP_URL}/192.168.9.13/menu")
    assert response.status_code == 200
    assert b"Client denied" in response.content
    assert b"/reservations/deny-aaaaaaaaaa04/edit" in response.content


def test_menu_ip_outside_range_not_found(admin_client, settings):
    _seed(settings)
    response = admin_client.get(f"{MAP_URL}/192.168.9.99/menu")
    assert response.status_code == 200
    assert b"Address not found" in response.content


def test_reserve_this_ip_link_prefills_new_reservation_form(operator_client, settings):
    _seed(settings)
    response = operator_client.get("/reservations/new", params={"ip": "192.168.9.14"})
    assert response.status_code == 200
    assert b"192.168.9.14" in response.content
