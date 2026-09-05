from conftest import OPERATOR_PASSWORD


def test_unauthenticated_redirects_to_login(client):
    response = client.get("/")
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_login_wrong_password_shows_error(client):
    response = client.post("/login", data={"username": "admin", "password": "wrong"})
    assert response.status_code == 401
    assert b"Invalid username or password" in response.content


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


def test_lease_context_menu_offers_reserve_action(admin_client):
    response = admin_client.get("/leases/192.168.1.51/menu")
    assert response.status_code == 200
    assert b"Reserve this lease" in response.content


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
