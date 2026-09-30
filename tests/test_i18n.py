import ast
import re
import string
from pathlib import Path

from conftest import ADMIN_PASSWORD, login
from sqlmodel import Session, select

from sandia import i18n
from sandia.i18n_es import ES
from sandia.models import User

SRC = Path(__file__).parent.parent / "src" / "sandia"
KEY = re.compile(r"""\bN?_\(\s*("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')""")


def _source_keys() -> set[str]:
    keys = set()
    for path in [*SRC.rglob("*.py"), *SRC.rglob("*.html")]:
        if path.name == "i18n_es.py":
            continue
        keys.update(ast.literal_eval(m.group(1)) for m in KEY.finditer(path.read_text()))
    return keys


def _placeholders(text: str) -> set[str]:
    return {field for _, field, _, _ in string.Formatter().parse(text) if field is not None}


def test_every_translatable_string_has_a_spanish_entry():
    missing = sorted(_source_keys() - ES.keys())
    assert not missing, f"Missing from i18n_es.ES: {missing}"


def test_spanish_entries_keep_the_same_placeholders():
    mismatched = [key for key, value in ES.items() if _placeholders(key) != _placeholders(value)]
    assert not mismatched


def test_gettext_defaults_to_english_and_switches_to_spanish():
    assert i18n._("Dashboard") == "Dashboard"
    token = i18n._lang.set("es")
    try:
        assert i18n._("Dashboard") == "Panel"
        assert i18n._("{n} matching events.", n=3) == "3 eventos coincidentes."
        assert i18n._("not in the catalog") == "not in the catalog"
    finally:
        i18n._lang.reset(token)


def test_template_gettext_escapes_values_not_catalog_text():
    rendered = i18n.template_gettext('Edit reservation "{name}"', name="<b>x</b>")
    assert rendered == 'Edit reservation "&lt;b&gt;x&lt;/b&gt;"'


def test_default_language_is_english(viewer_client):
    body = viewer_client.get("/").text
    assert '<html lang="en"' in body
    assert ">Dashboard<" in body
    assert 'aria-pressed="true"' in body.split('value="en"')[1].split(">")[0]


def test_switching_to_spanish_translates_and_persists(admin_client, app):
    response = admin_client.post("/account/language", data={"lang": "es", "next": "/devices"})
    assert response.status_code == 303
    assert response.headers["location"] == "/devices"

    body = admin_client.get("/").text
    assert '<html lang="es"' in body
    assert ">Panel<" in body
    assert "Leases activos" in body
    assert "Somehow, Another Network DHCP Is Alive." in body  # the backronym stays

    with Session(app.state.engine) as session:
        assert session.exec(select(User).where(User.username == "admin")).one().language == "es"


def test_language_survives_logout_and_login(client):
    login(client, "admin", ADMIN_PASSWORD)
    client.post("/account/language", data={"lang": "es", "next": "/"})
    client.post("/logout")

    login(client, "admin", ADMIN_PASSWORD)
    assert ">Panel<" in client.get("/").text


def test_anonymous_switch_on_login_page(client):
    client.post("/account/language", data={"lang": "es", "next": "/login"})
    body = client.get("/login").text
    assert "Iniciar sesión" in body
    assert "Usuario" in body


def test_invalid_language_and_external_next_fall_back(admin_client):
    response = admin_client.post("/account/language", data={"lang": "fr", "next": "//evil.example"})
    assert response.headers["location"] == "/"
    assert '<html lang="en"' in admin_client.get("/").text


def test_flash_messages_are_translated(operator_client):
    operator_client.post("/account/language", data={"lang": "es", "next": "/"})
    operator_client.post("/reservations/does-not-exist/delete")
    body = operator_client.get("/reservations").text
    assert "Reserva no encontrada." in body


def test_client_diagnostics_are_translated(viewer_client):
    viewer_client.post("/account/language", data={"lang": "es", "next": "/"})
    body = viewer_client.get("/diagnostics/client").text
    assert "Diagnóstico del cliente" in body
    assert "Evidencia insuficiente" in body
    assert "Selección de subnet" in body


def test_confirm_dialogs_are_valid_javascript_in_spanish(operator_client):
    operator_client.post("/account/language", data={"lang": "es", "next": "/"})
    body = operator_client.get("/reservations").text
    # tojson|forceescape: the attribute holds an HTML-escaped JSON string.
    assert "confirm(&#34;\\u00bfEliminar todas las reservas seleccionadas?&#34;)" in body


def test_ai_reply_language_follows_ui(viewer_client, app, monkeypatch):
    from sandia.models import AiSettings
    from sandia.routers import ai as ai_router

    with Session(app.state.engine) as session:
        session.add(AiSettings(id=1, ollama_url="http://10.0.0.5:11434", model="m"))
        session.commit()
    captured = {}

    async def fake_chat_stream(url, model, messages):
        captured["system"] = messages[0]["content"]
        yield "ok"

    monkeypatch.setattr(ai_router, "chat_stream", fake_chat_stream)
    viewer_client.post("/account/language", data={"lang": "es", "next": "/"})
    viewer_client.post("/ai/chat", json={"messages": [{"role": "user", "content": "hola"}]})

    assert "Reply in Spanish." in captured["system"]
