import json
import time

from conftest import (
    ADMIN_PASSWORD,
    OPERATOR_PASSWORD,
    VIEWER_PASSWORD,
    login,
    make_client,
)
from sqlmodel import Session, select

from sandia import ai
from sandia.models import AiSettings, AuditLog
from sandia.rollback_window import ROLLBACK_WINDOW

NEW_SUBNET = {"network": "10.9.0.0", "netmask": "255.255.255.0", "range_start": "10.9.0.10", "range_end": "10.9.0.20"}


def _propose(client, url="/subnets/new", data=NEW_SUBNET):
    response = client.post(url, data=data)
    assert response.status_code == 303
    location = response.headers["location"]
    assert location.startswith("/config/review/")
    return location


def test_editor_stages_a_change_without_touching_the_live_file(operator_client, settings):
    before = settings.dhcpd_conf_path.read_text()
    location = _propose(operator_client)
    assert settings.dhcpd_conf_path.read_text() == before

    page = operator_client.get(location)
    assert page.status_code == 200
    assert "Review change" in page.text
    assert "Configuration is valid." in page.text
    assert "10.9.0.0/24" in page.text
    assert "+subnet 10.9.0.0 netmask 255.255.255.0 {" in page.text


def test_apply_installs_audits_and_offers_rollback(operator_client, settings, app):
    location = _propose(operator_client)
    response = operator_client.post(f"{location}/apply")
    assert response.headers["location"] == "/subnets"
    assert "10.9.0.0" in settings.dhcpd_conf_path.read_text()
    with Session(app.state.engine) as session:
        assert session.exec(select(AuditLog).where(AuditLog.action == "subnet_create")).first() is not None

    page = operator_client.get("/subnets")
    assert "Subnet created. Configuration applied." in page.text
    assert 'action="/config/rollback"' in page.text
    # The token is single use.
    assert operator_client.get(location).status_code == 404


def test_cancel_discards(operator_client, settings):
    before = settings.dhcpd_conf_path.read_text()
    location = _propose(operator_client)
    response = operator_client.post(f"{location}/cancel")
    assert response.headers["location"] == "/subnets"
    assert settings.dhcpd_conf_path.read_text() == before
    assert operator_client.get(location).status_code == 404


def test_stale_change_is_not_applied(operator_client, settings):
    location = _propose(operator_client)
    settings.dhcpd_conf_path.write_text(settings.dhcpd_conf_path.read_text() + "\n# edited by hand\n")
    assert "Apply is disabled" in operator_client.get(location).text

    operator_client.post(f"{location}/apply")
    conf = settings.dhcpd_conf_path.read_text()
    assert "10.9.0.0" not in conf and "# edited by hand" in conf


def test_review_link_belongs_to_its_author(operator_client, app):
    location = _propose(operator_client)
    other = make_client(app)
    login(other, "admin", ADMIN_PASSWORD)
    assert other.get(location).status_code == 404
    assert other.post(f"{location}/apply").status_code == 404


def test_malformed_token_is_rejected(operator_client):
    assert operator_client.get("/config/review/..%2F..%2Fetc").status_code == 404
    assert operator_client.get("/config/review/short").status_code == 404


def test_viewer_cannot_review(viewer_client):
    assert viewer_client.get("/config/review/" + "a" * 24).status_code == 403


def test_raw_config_and_backup_restore_go_through_review(operator_client, settings):
    location = _propose(operator_client, "/config/raw/apply", {"text": "authoritative;\n"})
    page = operator_client.get(location)
    assert "Needs review" in page.text or "High risk" in page.text
    operator_client.post(f"{location}/apply")
    assert settings.dhcpd_conf_path.read_text() == "authoritative;\n"

    backup = next(settings.backup_dir.glob("dhcpd.conf.*"))
    location = _propose(operator_client, f"/backups/{backup.name}/restore", {})
    operator_client.post(f"{location}/apply")
    assert "192.168.1.0" in settings.dhcpd_conf_path.read_text()


def test_comment_only_raw_edit_is_low_risk(operator_client, settings):
    text = operator_client.get("/config/raw").text
    current = settings.dhcpd_conf_path.read_text()
    assert "authoritative" in text
    location = _propose(operator_client, "/config/raw/apply", {"text": current})
    assert "Low risk" in operator_client.get(location).text


def test_removing_a_subnet_with_active_leases_is_high_risk(operator_client):
    location = _propose(operator_client, "/subnets/192.168.1.0_255.255.255.0/delete", {})
    page = operator_client.get(location).text
    assert "High risk" in page
    assert "Active leases affected" in page
    assert "192.168.1.52" in page


def test_rollback_restores_the_previous_config(operator_client, settings):
    original = settings.dhcpd_conf_path.read_text()
    operator_client.post(f"{_propose(operator_client)}/apply")
    assert "10.9.0.0" in settings.dhcpd_conf_path.read_text()

    response = operator_client.post("/config/rollback", data={"next_url": "/subnets"})
    assert response.headers["location"] == "/subnets"
    assert settings.dhcpd_conf_path.read_text() == original
    assert 'action="/config/rollback"' not in operator_client.get("/subnets").text


def test_keep_clears_the_offer(operator_client, settings):
    operator_client.post(f"{_propose(operator_client)}/apply")
    operator_client.post("/config/rollback/keep", data={"next_url": "//evil.example"})
    assert 'action="/config/rollback"' not in operator_client.get("/").text
    assert operator_client.post("/config/rollback").headers["location"] == "/"
    assert "10.9.0.0" in settings.dhcpd_conf_path.read_text()


def test_offer_ends_after_the_window_or_a_later_change(operator_client, settings):
    operator_client.post(f"{_propose(operator_client)}/apply")
    record_path = settings.data_dir / "last-apply.json"
    record = json.loads(record_path.read_text())
    record["applied_at"] = time.time() - ROLLBACK_WINDOW - 1
    record_path.write_text(json.dumps(record))
    assert 'action="/config/rollback"' not in operator_client.get("/").text

    record["applied_at"] = time.time()
    record_path.write_text(json.dumps(record))
    assert 'action="/config/rollback"' in operator_client.get("/").text
    settings.dhcpd_conf_path.write_text(settings.dhcpd_conf_path.read_text() + "# later\n")
    assert 'action="/config/rollback"' not in operator_client.get("/").text


def test_viewers_never_see_the_rollback_banner(operator_client, app):
    operator_client.post(f"{_propose(operator_client)}/apply")
    viewer = make_client(app)
    login(viewer, "viewer", VIEWER_PASSWORD)
    assert 'action="/config/rollback"' not in viewer.get("/").text


def test_anomalies_page_lists_live_findings(admin_client, settings):
    settings.dhcpd_conf_path.write_text(
        settings.dhcpd_conf_path.read_text() + "host dup { hardware ethernet de:ad:00:00:00:01; fixed-address 192.168.1.10; }\n"
    )
    page = admin_client.get("/diagnostics/anomalies")
    assert page.status_code == 200
    assert "Duplicate reservation IP address" in page.text


def test_ai_chat_gets_the_pending_change_and_bounds(app, client, monkeypatch):
    with Session(app.state.engine) as session:
        session.add(AiSettings(id=1, ollama_url="http://10.0.0.5:11434", model="llama3.2"))
        session.commit()
    login(client, "operator", OPERATOR_PASSWORD)
    location = _propose(client)
    token = location.rsplit("/", 1)[1]
    captured = {}

    async def fake_chat_stream(url, model, messages):
        captured["messages"] = messages
        yield "ok"

    from sandia.routers import ai as ai_router

    monkeypatch.setattr(ai_router, "chat_stream", fake_chat_stream)
    question = "x" * (ai.MAX_QUESTION_CHARS + 500)
    client.post("/ai/chat", json={"messages": [{"role": "user", "content": question}], "review_token": token})
    system, user_message = captured["messages"]
    assert "## Pending change review (not applied yet)" in system["content"]
    assert "10.9.0.0/24 added" in system["content"]
    assert "<<<DATA" in system["content"] and "authoritative" in system["content"]
    assert "do not dismiss, downgrade or contradict a listed finding" in system["content"]
    assert len(user_message["content"]) < ai.MAX_QUESTION_CHARS + 100

    client.post("/ai/chat", json={"messages": [{"role": "user", "content": "hi"}], "review_token": "a" * 24})
    assert "no longer available" in captured["messages"][0]["content"]
