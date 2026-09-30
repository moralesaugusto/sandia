from conftest import ADMIN_PASSWORD, OPERATOR_PASSWORD, fetch_csrf_token, make_client


def test_unauthenticated_redirects_to_login(client):
    response = client.get("/")
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_login_wrong_password_shows_error(client):
    response = client.post("/login", data={"username": "admin", "password": "wrong"})
    assert response.status_code == 401
    assert b"Invalid username or password" in response.content


def test_session_cookie_is_hardened(client):
    response = client.post("/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    cookie = response.headers["set-cookie"].lower()
    assert cookie.startswith("sandia_session=")
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert "secure" in cookie


def test_session_cookie_not_secure_when_https_disabled(settings):
    from sqlmodel import Session, select

    from sandia.main import create_app
    from sandia.models import User
    from sandia.security import hash_password

    settings.enable_https = False
    app = create_app(settings)
    with Session(app.state.engine) as session:
        admin = session.exec(select(User)).one()
        admin.password_hash = hash_password(ADMIN_PASSWORD)
        session.add(admin)
        session.commit()
    client = make_client(app, base_url="http://testserver")
    response = client.post("/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    cookie = response.headers["set-cookie"].lower()
    assert cookie.startswith("sandia_session=")
    assert "secure" not in cookie


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


def test_interfaces_page_shows_empty_state_when_file_missing(admin_client, settings):
    assert not settings.interfaces_conf_path.exists()
    response = admin_client.get("/interfaces")
    assert response.status_code == 200
    assert b"doesn't exist yet" in response.content


def test_operator_can_update_interfaces(operator_client, settings):
    response = operator_client.post("/interfaces", data={"interfaces": "eth0, eth1"})
    assert response.status_code == 303

    text = settings.interfaces_conf_path.read_text()
    assert 'INTERFACESv4="eth0 eth1"' in text

    page = operator_client.get("/interfaces")
    assert b'value="eth0 eth1"' in page.content


def test_interfaces_page_flags_mismatched_subnet_tag(operator_client, settings):
    operator_client.post("/interfaces", data={"interfaces": "eth0"})
    operator_client.post(
        "/subnets/192.168.1.0_255.255.255.0/edit",
        data={"range_start": "192.168.1.100", "range_end": "192.168.1.200", "interface": "eth9"},
    )
    response = operator_client.get("/interfaces")
    assert response.status_code == 200
    assert b"not listening" in response.content


def test_interfaces_preserves_unrelated_file_content(operator_client, settings):
    settings.interfaces_conf_path.write_text('#DHCPDv4_CONF=/etc/dhcp/dhcpd.conf\nINTERFACESv4="eth0"\n')
    operator_client.post("/interfaces", data={"interfaces": "eth5"})
    text = settings.interfaces_conf_path.read_text()
    assert "#DHCPDv4_CONF=/etc/dhcp/dhcpd.conf" in text
    assert 'INTERFACESv4="eth5"' in text


def test_viewer_cannot_update_interfaces(viewer_client):
    response = viewer_client.post("/interfaces", data={"interfaces": "eth0"})
    assert response.status_code == 403


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


def test_reservations_subnet_filter_defaults_to_all(admin_client):
    # Fixture has "printer" nested in 192.168.1.0/24, "server1" and "laptop"
    # global (laptop is inside a group, not a subnet).
    response = admin_client.get("/reservations")
    assert b"printer" in response.content
    assert b"server1" in response.content
    assert b"laptop" in response.content


def test_reservations_subnet_filter_narrows_to_one_subnet(admin_client):
    response = admin_client.get("/reservations", params={"subnet_key": "192.168.1.0_255.255.255.0"})
    assert b"printer" in response.content
    assert b"server1" not in response.content
    assert b"laptop" not in response.content


def test_reservations_subnet_filter_global_only(admin_client):
    response = admin_client.get("/reservations", params={"subnet_key": "__global__"})
    assert b"printer" not in response.content
    assert b"server1" in response.content
    assert b"laptop" in response.content


def test_reservations_csv_export_respects_subnet_filter(admin_client):
    response = admin_client.get("/reservations/export.csv", params={"subnet_key": "__global__"})
    assert b"printer" not in response.content
    assert b"server1" in response.content


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


def test_leases_page_defaults_to_active_state_only(admin_client):
    # Fixture: .50 and .52 are active, .51 is free.
    response = admin_client.get("/leases")
    assert b"192.168.1.50" in response.content
    assert b"192.168.1.52" in response.content
    assert b"192.168.1.51" not in response.content


def test_leases_state_filter_can_show_all(admin_client):
    response = admin_client.get("/leases", params={"state": ""})
    assert b"192.168.1.50" in response.content
    assert b"192.168.1.51" in response.content
    assert b"192.168.1.52" in response.content


def test_leases_state_filter_can_narrow_to_free(admin_client):
    response = admin_client.get("/leases/table", params={"state": "free"})
    assert b"192.168.1.51" in response.content
    assert b"192.168.1.50" not in response.content
    assert b"192.168.1.52" not in response.content


def test_leases_csv_export_respects_state_filter(admin_client):
    response = admin_client.get("/leases/export.csv", params={"state": "free"})
    assert b"192.168.1.51" in response.content
    assert b"192.168.1.50" not in response.content


def test_leases_sort_by_ip_ascending_is_numeric_not_lexical(admin_client):
    response = admin_client.get("/leases/table", params={"state": "", "sort": "ip"})
    body = response.content
    assert body.index(b"192.168.1.50") < body.index(b"192.168.1.51") < body.index(b"192.168.1.52")


def test_leases_sort_by_ip_descending(admin_client):
    response = admin_client.get("/leases/table", params={"state": "", "sort": "-ip"})
    body = response.content
    assert body.index(b"192.168.1.52") < body.index(b"192.168.1.51") < body.index(b"192.168.1.50")


def test_leases_sort_by_mac(admin_client):
    # fixture MACs: .50 -> 00:11:22:33:44:55, .51 -> aa:bb:cc:dd:ee:01, .52 -> aa:bb:cc:dd:ee:02
    response = admin_client.get("/leases/table", params={"state": "", "sort": "mac"})
    body = response.content
    assert body.index(b"192.168.1.50") < body.index(b"192.168.1.51") < body.index(b"192.168.1.52")


def test_leases_unknown_sort_key_is_ignored_not_an_error(admin_client):
    response = admin_client.get("/leases/table", params={"state": "", "sort": "not-a-real-column"})
    assert response.status_code == 200
    assert b"192.168.1.50" in response.content


def test_leases_table_headers_are_clickable_and_show_sort_indicator(admin_client):
    response = admin_client.get("/leases", params={"sort": "ip"})
    assert response.status_code == 200
    assert b"sortTable('leases-filter-form', 'ip')" in response.content
    assert b"&#9650;" in response.content  # ascending-sort arrow on the active column


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


def test_about_page_shows_builtin_only_status_by_default(admin_client):
    response = admin_client.get("/about")
    assert response.status_code == 200
    assert b"Built-in list only" in response.content
    assert b"Download OUI database" in response.content


def test_about_page_explains_data_sources_and_log_window(viewer_client, settings):
    from sandia.diagnostics.dhcp_log import MAX_LOG_BYTES

    body = viewer_client.get("/about").text
    assert "Where the data comes from" in body
    assert str(settings.dhcp_log_path) in body
    assert "not found" in body
    assert str(settings.db_path) in body
    assert "are not stored in a database" in body
    assert f"last {MAX_LOG_BYTES / 1_000_000:g} MB of the log" in body

    settings.dhcp_log_path.write_text("x" * 300_000)
    body = viewer_client.get("/about").text
    assert "found (0.3 MB)" in body


def test_operator_can_trigger_oui_refresh(operator_client, monkeypatch):
    from test_oui_cache import _FakeResponse

    from sandia import oui_cache

    csv_text = "Registry,Assignment,Organization Name,Organization Address\nMA-L,AABBCC,Test Vendor,Somewhere\n"
    monkeypatch.setattr(oui_cache.urllib.request, "urlopen", lambda req, timeout=None: _FakeResponse(csv_text.encode()))

    response = operator_client.post("/about/oui-refresh")
    assert response.status_code == 303

    listing = operator_client.get("/about")
    assert b"OUI database refresh started" in listing.content


def test_refresh_reports_error_when_already_in_progress(operator_client, monkeypatch):
    from sandia import oui_cache

    monkeypatch.setattr(oui_cache, "start_refresh", lambda data_dir: False)

    response = operator_client.post("/about/oui-refresh")
    assert response.status_code == 303

    listing = operator_client.get("/about")
    assert b"already in progress" in listing.content


def test_viewer_cannot_trigger_oui_refresh(viewer_client):
    response = viewer_client.post("/about/oui-refresh")
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
    fetch_csrf_token(fresh)
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


def test_dashboard_and_sidebar_show_tagline(viewer_client):
    body = viewer_client.get("/").text
    assert body.count("Somehow, Another Network DHCP Is Alive.") == 2  # sidebar + dashboard heading
