from conftest import ADMIN_PASSWORD, login
from sqlmodel import Session, select

from sandia.models import User


def test_default_theme_is_dark(client):
    response = client.get("/login")
    assert response.status_code == 200
    assert b'class="h-full bg-slate-950"' in response.content
    assert b" light\"" not in response.content


def test_authenticated_toggle_switches_html_class_and_persists_to_db(admin_client, app):
    response = admin_client.post("/account/theme", data={"theme": "light", "next": "/"})
    assert response.status_code == 303
    assert response.headers["location"] == "/"

    dashboard = admin_client.get("/")
    assert b'class="h-full bg-slate-950 light"' in dashboard.content
    assert b"Light mode" in dashboard.content

    with Session(app.state.engine) as session:
        user = session.exec(select(User).where(User.username == "admin")).first()
        assert user.theme == "light"


def test_theme_persists_across_a_brand_new_session(client, app):
    login(client, "admin", ADMIN_PASSWORD)
    client.post("/account/theme", data={"theme": "light", "next": "/"})
    client.post("/logout")

    login(client, "admin", ADMIN_PASSWORD)
    dashboard = client.get("/")
    assert b'class="h-full bg-slate-950 light"' in dashboard.content


def test_anonymous_toggle_on_login_page_works_without_a_user(client):
    response = client.post("/account/theme", data={"theme": "light", "next": "/login"})
    assert response.status_code == 303
    assert response.headers["location"] == "/login"

    login_page = client.get("/login")
    assert b'class="h-full bg-slate-950 light"' in login_page.content


def test_invalid_theme_value_falls_back_to_dark(admin_client):
    admin_client.post("/account/theme", data={"theme": "light", "next": "/"})
    admin_client.post("/account/theme", data={"theme": "not-a-real-theme", "next": "/"})

    dashboard = admin_client.get("/")
    assert b'class="h-full bg-slate-950"' in dashboard.content
    assert b" light\"" not in dashboard.content


def test_theme_toggle_rejects_external_redirect_target(admin_client):
    response = admin_client.post(
        "/account/theme", data={"theme": "light", "next": "https://evil.example/"}
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/"


def test_login_does_not_clobber_a_theme_already_chosen_this_session(client, app):
    client.post("/account/theme", data={"theme": "light", "next": "/login"})
    with Session(app.state.engine) as session:
        user = session.exec(select(User).where(User.username == "admin")).first()
        assert user.theme == "dark"  # never toggled while authenticated

    login(client, "admin", ADMIN_PASSWORD)
    dashboard = client.get("/")
    assert b'class="h-full bg-slate-950 light"' in dashboard.content
