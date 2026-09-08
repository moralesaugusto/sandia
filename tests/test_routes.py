from conftest import OPERATOR_PASSWORD


def test_unauthenticated_redirects_to_login(client):
    response = client.get("/")
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_login_wrong_password_shows_error(client):
    response = client.post("/login", data={"username": "admin", "password": "wrong"})
    assert response.status_code == 401
    assert b"Invalid username or password" in response.content


def test_flash_messages_render_as_toast_data_attribute(operator_client):
    response = operator_client.post(
        "/subnets/new",
        data={
            "network": "172.31.0.0",
            "netmask": "255.255.255.0",
            "range_start": "172.31.0.10",
            "range_end": "172.31.0.50",
        },
    )
    assert response.status_code == 303
    listing = operator_client.get("/subnets")
    assert b'data-flash-message="Subnet created' in listing.content
    assert b'data-flash-kind="success"' in listing.content
    assert b'id="toast-container"' in listing.content

    # the flash is one-shot: a second request must not re-show the same toast
    second = operator_client.get("/subnets")
    assert b"data-flash-message" not in second.content


def test_login_locks_out_after_repeated_failures(client):
    from sandia import rate_limit

    rate_limit.clear_failures("lockout-target")
    for _ in range(rate_limit.MAX_ATTEMPTS):
        client.post("/login", data={"username": "lockout-target", "password": "wrong"})

    response = client.post("/login", data={"username": "lockout-target", "password": "wrong"})
    assert response.status_code == 429
    assert b"Too many failed attempts" in response.content


def test_dashboard_shows_seeded_subnet(admin_client):
    response = admin_client.get("/")
    assert response.status_code == 200
    assert b"192.168.1.0" in response.content


def test_viewer_cannot_reach_operator_routes(viewer_client):
    response = viewer_client.get("/subnets/new")
    assert response.status_code == 403

    response = viewer_client.post(
        "/subnets/new",
        data={"network": "10.0.0.0", "netmask": "255.255.255.0", "range_start": "10.0.0.10", "range_end": "10.0.0.20"},
    )
    assert response.status_code == 403


def test_viewer_cannot_reach_admin_routes(viewer_client, operator_client):
    assert viewer_client.get("/users").status_code == 403
    assert operator_client.get("/users").status_code == 403


def test_operator_can_create_edit_delete_subnet(operator_client):
    create = operator_client.post(
        "/subnets/new",
        data={
            "network": "10.0.0.0",
            "netmask": "255.255.255.0",
            "range_start": "10.0.0.10",
            "range_end": "10.0.0.100",
            "routers": "10.0.0.1",
        },
    )
    assert create.status_code == 303
    assert create.headers["location"] == "/subnets"

    listing = operator_client.get("/subnets")
    assert b"10.0.0.0" in listing.content

    edit = operator_client.post(
        "/subnets/10.0.0.0_255.255.255.0/edit",
        data={"range_start": "10.0.0.10", "range_end": "10.0.0.200", "routers": "10.0.0.1"},
    )
    assert edit.status_code == 303

    listing = operator_client.get("/subnets")
    assert b"10.0.0.200" in listing.content
    assert edit.headers["location"] == "/subnets"

    delete = operator_client.post("/subnets/10.0.0.0_255.255.255.0/delete")
    assert delete.status_code == 303
    listing = operator_client.get("/subnets")
    assert b"10.0.0.0 / 255.255.255.0" not in listing.content


def test_operator_can_create_reservation(operator_client):
    response = operator_client.post(
        "/reservations/new",
        data={"name": "newclient", "mac": "de:ad:be:ef:00:01", "fixed_address": "192.168.1.99", "subnet_key": ""},
    )
    assert response.status_code == 303
    listing = operator_client.get("/reservations")
    assert b"newclient" in listing.content
    assert b"de:ad:be:ef:00:01" in listing.content


def test_reservation_details_shows_known_fields(admin_client):
    response = admin_client.get("/reservations/printer/details")
    assert response.status_code == 200
    assert b"00:11:22:33:44:55" in response.content
    assert b"192.168.1.50" in response.content
    assert b"192.168.1.0/255.255.255.0" in response.content


def test_reservation_details_viewer_can_access(viewer_client):
    response = viewer_client.get("/reservations/printer/details")
    assert response.status_code == 200
    assert b"192.168.1.50" in response.content


def test_reservation_details_unknown_host(admin_client):
    response = admin_client.get("/reservations/does-not-exist/details")
    assert response.status_code == 200
    assert b"not found" in response.content


def test_reservation_client_options_round_trip(operator_client, settings):
    operator_client.post(
        "/reservations/new",
        data={
            "name": "pxe-client",
            "mac": "aa:bb:cc:dd:ee:ff",
            "fixed_address": "192.168.1.80",
            "subnet_key": "",
            "client_hostname": "pxeclient",
            "next_server": "192.168.1.5",
            "boot_filename": "pxelinux.0",
            "extra_options": 'option domain-name-servers 1.1.1.1;',
        },
    )
    conf = settings.dhcpd_conf_path.read_text()
    assert 'option host-name "pxeclient";' in conf
    assert "next-server 192.168.1.5;" in conf
    assert 'filename "pxelinux.0";' in conf
    assert "option domain-name-servers 1.1.1.1;" in conf

    edit_page = operator_client.get("/reservations/pxe-client/edit")
    assert b"pxeclient" in edit_page.content
    assert b"192.168.1.5" in edit_page.content
    assert b"pxelinux.0" in edit_page.content

    # clearing a field on edit must remove it, not leave it stale
    operator_client.post(
        "/reservations/pxe-client/edit",
        data={
            "mac": "aa:bb:cc:dd:ee:ff",
            "fixed_address": "192.168.1.80",
            "client_hostname": "",
            "next_server": "",
            "boot_filename": "",
            "extra_options": "",
        },
    )
    conf_after = settings.dhcpd_conf_path.read_text()
    assert "host-name" not in conf_after
    assert "next-server" not in conf_after
    assert "domain-name-servers 1.1.1.1" not in conf_after


def test_subnet_client_options_round_trip(operator_client, settings):
    operator_client.post(
        "/subnets/new",
        data={
            "network": "10.9.0.0",
            "netmask": "255.255.255.0",
            "range_start": "10.9.0.10",
            "range_end": "10.9.0.50",
            "ntp_servers": "pool.ntp.org",
            "next_server": "10.9.0.5",
            "boot_filename": "pxelinux.0",
            "default_lease_time": "300",
            "max_lease_time": "3600",
            "extra_options": 'option tftp-server-name "tftp.local";',
        },
    )
    conf = settings.dhcpd_conf_path.read_text()
    assert "option ntp-servers pool.ntp.org;" in conf
    assert "next-server 10.9.0.5;" in conf
    assert "default-lease-time 300;" in conf
    assert "max-lease-time 3600;" in conf
    assert 'option tftp-server-name "tftp.local";' in conf


def test_subnet_interface_tag_round_trip(operator_client, settings):
    operator_client.post(
        "/subnets/new",
        data={
            "network": "192.168.89.0",
            "netmask": "255.255.255.0",
            "range_start": "192.168.89.10",
            "range_end": "192.168.89.50",
            "interface": "eth2",
        },
    )
    conf = settings.dhcpd_conf_path.read_text()
    assert "# interface: eth2" in conf

    listing = operator_client.get("/subnets")
    assert b"eth2" in listing.content

    edit_page = operator_client.get("/subnets/192.168.89.0_255.255.255.0/edit")
    assert b'value="eth2"' in edit_page.content

    # changing it should not leave the old tag behind
    operator_client.post(
        "/subnets/192.168.89.0_255.255.255.0/edit",
        data={"range_start": "192.168.89.10", "range_end": "192.168.89.50", "interface": "eth3"},
    )
    conf_after = settings.dhcpd_conf_path.read_text()
    assert "# interface: eth3" in conf_after
    assert "# interface: eth2" not in conf_after


def test_bulk_delete_reservations(operator_client, settings):
    operator_client.post(
        "/reservations/new",
        data={"name": "bulk-a", "mac": "aa:aa:aa:aa:aa:01", "fixed_address": "192.168.1.71", "subnet_key": ""},
    )
    operator_client.post(
        "/reservations/new",
        data={"name": "bulk-b", "mac": "aa:aa:aa:aa:aa:02", "fixed_address": "192.168.1.72", "subnet_key": ""},
    )

    response = operator_client.post("/reservations/bulk-delete", data={"names": ["bulk-a", "bulk-b"]})
    assert response.status_code == 303

    conf = settings.dhcpd_conf_path.read_text()
    assert "bulk-a" not in conf
    assert "bulk-b" not in conf


def test_bulk_delete_with_no_selection_shows_error(operator_client):
    response = operator_client.post("/reservations/bulk-delete", data={})
    assert response.status_code == 303
    listing = operator_client.get("/reservations")
    assert b"No reservations selected" in listing.content


def test_viewer_cannot_bulk_delete(viewer_client):
    response = viewer_client.post("/reservations/bulk-delete", data={"names": ["whatever"]})
    assert response.status_code == 403


def test_duplicate_reservation_name_is_rejected(operator_client):
    operator_client.post(
        "/reservations/new",
        data={"name": "dupe", "mac": "aa:aa:aa:aa:aa:aa", "fixed_address": "192.168.1.61", "subnet_key": ""},
    )
    response = operator_client.post(
        "/reservations/new",
        data={"name": "dupe", "mac": "bb:bb:bb:bb:bb:bb", "fixed_address": "192.168.1.62", "subnet_key": ""},
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/reservations/new"


def test_invalid_config_edit_does_not_touch_live_file(operator_client, settings):
    before = settings.dhcpd_conf_path.read_text()

    response = operator_client.post(
        "/config/raw/apply",
        data={"text": before + "\nFORCE_INVALID\n"},
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/config/raw"
    assert settings.dhcpd_conf_path.read_text() == before


def test_raw_config_diff_shows_added_line(operator_client, settings):
    from sandia.config_store import load_live_config
    from sandia.dhcpd import serialize

    current = serialize(load_live_config(settings))
    response = operator_client.post(
        "/config/raw/diff",
        data={"text": current + "\ndefault-lease-time 1200;\n"},
    )
    assert response.status_code == 200
    assert b"default-lease-time 1200;" in response.content


def test_raw_config_diff_no_changes(operator_client, settings):
    from sandia.config_store import load_live_config
    from sandia.dhcpd import serialize

    current = serialize(load_live_config(settings))
    response = operator_client.post("/config/raw/diff", data={"text": current})
    assert response.status_code == 200
    assert b"No changes" in response.content


def test_leases_page_lists_fixture_leases(admin_client):
    response = admin_client.get("/leases")
    assert response.status_code == 200
    assert b"192.168.1.50" in response.content
    assert b"192.168.1.52" in response.content


def test_leases_search_filters_table(admin_client):
    response = admin_client.get("/leases/table", params={"q": "192.168.1.52"})
    assert b"192.168.1.52" in response.content
    assert b"192.168.1.51" not in response.content


def test_global_search_matches_reservation_and_lease(admin_client):
    response = admin_client.get("/search/suggest", params={"q": "printer"})
    assert response.status_code == 200
    assert b"Reservations" in response.content
    assert b"/reservations/printer/edit" in response.content
    assert b"Leases" in response.content


def test_global_search_matches_by_ip(admin_client):
    response = admin_client.get("/search/suggest", params={"q": "192.168.1.50"})
    assert response.status_code == 200
    assert b"printer" in response.content


def test_global_search_no_match(admin_client):
    response = admin_client.get("/search/suggest", params={"q": "no-such-thing-xyz"})
    assert response.status_code == 200
    assert b"No matches" in response.content


def test_global_search_empty_query_returns_nothing(admin_client):
    response = admin_client.get("/search/suggest", params={"q": ""})
    assert response.status_code == 200
    assert response.content.strip() == b""


def test_lease_context_menu_offers_reserve_action(admin_client):
    response = admin_client.get("/leases/192.168.1.51/menu")
    assert response.status_code == 200
    assert b"Reserve this lease" in response.content


def test_lease_context_menu_links_to_edit_when_already_reserved(admin_client):
    # 192.168.1.50's MAC (00:11:22:33:44:55) matches the fixture's "printer" reservation.
    response = admin_client.get("/leases/192.168.1.50/menu")
    assert response.status_code == 200
    assert b"Edit reservation" in response.content
    assert b"/reservations/printer/edit" in response.content
    assert b"Reserve this lease" not in response.content


def test_reserve_from_lease_prefills_form(operator_client):
    response = operator_client.get(
        "/reservations/new", params={"mac": "aa:bb:cc:dd:ee:01", "ip": "192.168.1.51", "hostname": ""}
    )
    assert response.status_code == 200
    assert b"aa:bb:cc:dd:ee:01" in response.content
    assert b"192.168.1.51" in response.content


def test_deny_lease_creates_deny_host(operator_client, settings):
    response = operator_client.post("/leases/192.168.1.51/deny")
    assert response.status_code == 303

    updated = settings.dhcpd_conf_path.read_text()
    assert "deny-aabbccddee01" in updated
    assert "deny booting;" in updated


def test_backups_created_after_first_apply(operator_client, settings):
    operator_client.post(
        "/subnets/new",
        data={"network": "172.16.0.0", "netmask": "255.255.255.0", "range_start": "172.16.0.10", "range_end": "172.16.0.50"},
    )
    listing = operator_client.get("/backups")
    assert listing.status_code == 200
    assert b"dhcpd.conf." in listing.content


def test_clean_leases_removes_stale_history(operator_client, settings):
    before = settings.leases_path.read_text()
    assert before.count("lease 192.168.1.50") == 2  # the fixture has one superseded duplicate

    response = operator_client.post("/leases/clean")
    assert response.status_code == 303

    after = settings.leases_path.read_text()
    assert after.count("lease 192.168.1.50") == 1
    assert "192.168.1.51" in after  # untouched leases still present
    assert "192.168.1.52" in after

    backups = list(settings.backup_dir.glob("dhcpd.leases.*"))
    assert len(backups) == 1
    assert backups[0].read_text() == before

    listing = operator_client.get("/leases")
    assert b"Cleaned 1 stale lease record" in listing.content


def test_clean_leases_is_a_no_op_when_already_clean(operator_client, settings):
    operator_client.post("/leases/clean")  # first pass removes the one duplicate
    response = operator_client.post("/leases/clean")  # second pass: nothing left to clean
    assert response.status_code == 303
    listing = operator_client.get("/leases")
    assert b"already clean" in listing.content


def test_viewer_cannot_clean_leases(viewer_client):
    response = viewer_client.post("/leases/clean")
    assert response.status_code == 403


def test_admin_can_manage_users(admin_client):
    create = admin_client.post("/users/new", data={"username": "newop", "password": "somepassword", "role": "operator"})
    assert create.status_code == 303
    listing = admin_client.get("/users")
    assert b"newop" in listing.content


def test_audit_log_records_actions(admin_client):
    admin_client.post(
        "/subnets/new",
        data={"network": "192.168.9.0", "netmask": "255.255.255.0", "range_start": "192.168.9.10", "range_end": "192.168.9.50"},
    )
    response = admin_client.get("/audit")
    assert response.status_code == 200
    assert b"subnet_create" in response.content


def test_any_role_can_change_own_password(operator_client):
    response = operator_client.post(
        "/account/password",
        data={
            "current_password": OPERATOR_PASSWORD,
            "new_password": "brand-new-password-1",
            "confirm_password": "brand-new-password-1",
        },
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/account/password"

    # old password no longer works, new one does
    fresh = operator_client
    fresh.cookies.clear()
    assert fresh.post("/login", data={"username": "operator", "password": OPERATOR_PASSWORD}).status_code == 401
    assert fresh.post("/login", data={"username": "operator", "password": "brand-new-password-1"}).status_code == 303


def test_change_password_rejects_wrong_current_password(operator_client):
    response = operator_client.post(
        "/account/password",
        data={"current_password": "totally-wrong", "new_password": "whatever12345", "confirm_password": "whatever12345"},
    )
    assert response.status_code == 303
    listing = operator_client.get("/account/password")
    assert b"Current password is incorrect" in listing.content


def test_change_password_rejects_mismatched_confirmation(operator_client):
    response = operator_client.post(
        "/account/password",
        data={"current_password": OPERATOR_PASSWORD, "new_password": "abc12345", "confirm_password": "different12345"},
    )
    assert response.status_code == 303
    listing = operator_client.get("/account/password")
    assert b"do not match" in listing.content
