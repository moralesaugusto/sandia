import os

import pytest

from sandia import main


def test_permission_error_message_is_actionable():
    exc = PermissionError(13, "Permission denied")
    exc.filename = "/var/lib/sandia"

    message = main._explain_permission_error(exc)

    assert "/var/lib/sandia" in message
    assert "sandia --dummy" in message
    assert "SANDIA_DATA_DIR" in message
    assert "sudo" in message


def test_run_exits_cleanly_instead_of_raising_traceback(monkeypatch, capsys):
    def fake_create_app(settings):
        exc = PermissionError(13, "Permission denied")
        exc.filename = "/var/lib/sandia"
        raise exc

    monkeypatch.setattr(main, "create_app", fake_create_app)

    with pytest.raises(SystemExit) as exc_info:
        main.run(argv=[])

    assert exc_info.value.code == 1
    assert "Permission denied" in capsys.readouterr().err


def test_dummy_cli_flag_sets_env_var(monkeypatch):
    monkeypatch.delenv("SANDIA_DUMMY_DATA", raising=False)

    def fake_create_app(settings):
        raise SystemExit(0)  # stop before actually starting a server

    monkeypatch.setattr(main, "create_app", fake_create_app)

    with pytest.raises(SystemExit):
        main.run(argv=["--dummy"])

    assert os.environ["SANDIA_DUMMY_DATA"] == "1"


def test_version_flag_prints_version_and_exits(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main.run(argv=["--version"])

    assert exc_info.value.code == 0
    assert "sandia" in capsys.readouterr().out


def test_set_password_cli_updates_existing_user(tmp_path, monkeypatch):
    from sqlmodel import Session, select

    from sandia.config import Settings
    from sandia.db import create_db_engine
    from sandia.models import User
    from sandia.security import hash_password, verify_password

    monkeypatch.setenv("SANDIA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("SANDIA_DUMMY_DATA", raising=False)

    settings = Settings()
    engine = create_db_engine(settings)
    with Session(engine) as session:
        session.add(User(username="admin", password_hash=hash_password("old-password"), role="admin"))
        session.commit()

    passwords = iter(["new-secret-password", "new-secret-password"])
    monkeypatch.setattr("getpass.getpass", lambda *args, **kwargs: next(passwords))

    main.run(argv=["--set-password", "admin"])

    with Session(engine) as session:
        user = session.exec(select(User).where(User.username == "admin")).first()
        assert verify_password("new-secret-password", user.password_hash)
        assert not verify_password("old-password", user.password_hash)


def test_set_password_cli_rejects_mismatched_confirmation(tmp_path, monkeypatch, capsys):
    from sqlmodel import Session

    from sandia.config import Settings
    from sandia.db import create_db_engine
    from sandia.models import User
    from sandia.security import hash_password

    monkeypatch.setenv("SANDIA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("SANDIA_DUMMY_DATA", raising=False)

    settings = Settings()
    engine = create_db_engine(settings)
    with Session(engine) as session:
        session.add(User(username="admin", password_hash=hash_password("old-password"), role="admin"))
        session.commit()

    passwords = iter(["one-password", "a-different-password"])
    monkeypatch.setattr("getpass.getpass", lambda *args, **kwargs: next(passwords))

    with pytest.raises(SystemExit) as exc_info:
        main.run(argv=["--set-password", "admin"])

    assert exc_info.value.code == 1
    assert "did not match" in capsys.readouterr().err


def test_set_password_cli_unknown_user(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SANDIA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("SANDIA_DUMMY_DATA", raising=False)

    with pytest.raises(SystemExit) as exc_info:
        main.run(argv=["--set-password", "nobody"])

    assert exc_info.value.code == 1
    assert "No such user" in capsys.readouterr().err
