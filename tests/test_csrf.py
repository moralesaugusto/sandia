import re

from conftest import ADMIN_PASSWORD, make_client

NEW_SUBNET = {
    "network": "10.9.0.0",
    "netmask": "255.255.255.0",
    "range_start": "10.9.0.10",
    "range_end": "10.9.0.20",
    "routers": "10.9.0.1",
}


def _form_token(client, path):
    return re.search(r'name="csrf_token" value="([^"]+)"', client.get(path).text).group(1)


def test_post_without_token_is_rejected(admin_client, settings):
    del admin_client.headers["X-CSRF-Token"]
    response = admin_client.post("/subnets/new", data=NEW_SUBNET)
    assert response.status_code == 403
    assert "10.9.0.0" not in settings.dhcpd_conf_path.read_text()


def test_post_with_invalid_token_is_rejected(admin_client, settings):
    admin_client.headers["X-CSRF-Token"] = "not-the-token"
    assert admin_client.post("/subnets/new", data=NEW_SUBNET).status_code == 403
    del admin_client.headers["X-CSRF-Token"]
    assert admin_client.post("/subnets/new", data={**NEW_SUBNET, "csrf_token": "not-the-token"}).status_code == 403
    assert "10.9.0.0" not in settings.dhcpd_conf_path.read_text()


def test_post_with_valid_form_field_token_is_accepted(admin_client, settings):
    token = admin_client.headers.pop("X-CSRF-Token")
    review = admin_client.post("/subnets/new", data={**NEW_SUBNET, "csrf_token": token})
    assert review.status_code == 303
    response = admin_client.post(f"{review.headers['location']}/apply", data={"csrf_token": token})
    assert response.status_code == 303
    assert "10.9.0.0" in settings.dhcpd_conf_path.read_text()


def test_htmx_header_token_is_accepted(admin_client):
    response = admin_client.post(
        "/config/raw/validate", data={"text": "authoritative;\n"}, headers={"HX-Request": "true"}
    )
    assert response.status_code == 200


def test_ai_chat_requires_token(admin_client):
    token = admin_client.headers.pop("X-CSRF-Token")
    body = {"messages": [{"role": "user", "content": "hi"}]}
    assert admin_client.post("/ai/chat", json=body).status_code == 403
    # With the header it gets past CSRF to the "not configured" answer.
    assert admin_client.post("/ai/chat", json=body, headers={"X-CSRF-Token": token}).status_code == 409


def test_login_requires_token(app):
    client = make_client(app)
    del client.headers["X-CSRF-Token"]
    assert client.post("/login", data={"username": "admin", "password": ADMIN_PASSWORD}).status_code == 403


def test_token_rotates_on_login(app):
    client = make_client(app)
    before = client.headers["X-CSRF-Token"]
    assert client.post("/login", data={"username": "admin", "password": ADMIN_PASSWORD}).status_code == 303
    assert _form_token(client, "/account/password") != before
    # The pre-login token no longer works.
    assert client.post("/logout").status_code == 403


def test_pages_carry_the_token_for_forms_and_htmx(admin_client):
    page = admin_client.get("/service").text
    token = admin_client.headers["X-CSRF-Token"]
    assert f'name="csrf_token" value="{token}"' in page
    assert f'hx-headers=\'{{"X-CSRF-Token": "{token}"}}\'' in page
