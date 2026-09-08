import argparse
import os
import secrets
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from sqlmodel import Session, select

from . import __version__
from .config import Settings
from .db import create_db_engine
from .dummy_data import seed_dummy_data
from .errors import register_exception_handlers
from .ip_map import MAX_CELLS
from .models import User
from .routers import (
    about,
    audit_router,
    auth,
    backups,
    dashboard,
    diagnostics,
    global_settings,
    interfaces,
    leases_router,
    raw_config,
    reservations,
    search,
    service,
    subnets,
    users,
)
from .security import hash_password
from .tls import ensure_self_signed_cert
from .utilization import utilization_color
from .vendors import configure as configure_vendors
from .vendors import lookup_vendor

BASE_DIR = Path(__file__).parent


def _load_or_create_session_secret(settings: Settings) -> str:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    path = settings.session_secret_path
    if path.exists():
        return path.read_text().strip()
    secret = secrets.token_urlsafe(32)
    path.write_text(secret)
    path.chmod(0o600)
    return secret


def _bootstrap_admin(engine, settings: Settings) -> None:
    with Session(engine) as session:
        if session.exec(select(User)).first() is not None:
            return
        print("Created initial admin user with fixed default credentials: admin / admin")
        print("SECURITY WARNING: change this before exposing the app beyond localhost - use the")
        print("'Change password' link once logged in, or run 'sandia --set-password admin'.")
        admin = User(username="admin", password_hash=hash_password("admin"), role="admin")
        session.add(admin)
        session.commit()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    if settings.dummy_data:
        seed_dummy_data(settings)

    app = FastAPI(title="Sandia", version=__version__)
    register_exception_handlers(app)
    app.state.settings = settings
    app.state.engine = create_db_engine(settings)
    configure_vendors(settings.data_dir)
    app.state.templates = Jinja2Templates(directory=BASE_DIR / "templates")
    app.state.templates.env.globals["app_version"] = __version__
    app.state.templates.env.globals["utilization_color"] = utilization_color
    app.state.templates.env.globals["max_cells"] = MAX_CELLS
    app.state.templates.env.filters["vendor"] = lookup_vendor

    _bootstrap_admin(app.state.engine, settings)

    app.add_middleware(SessionMiddleware, secret_key=_load_or_create_session_secret(settings))
    app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

    app.include_router(auth.router)
    app.include_router(dashboard.router)
    app.include_router(global_settings.router)
    app.include_router(subnets.router)
    app.include_router(reservations.router)
    app.include_router(leases_router.router)
    app.include_router(raw_config.router)
    app.include_router(service.router)
    app.include_router(backups.router)
    app.include_router(users.router)
    app.include_router(audit_router.router)
    app.include_router(about.router)
    app.include_router(search.router)
    app.include_router(interfaces.router)
    app.include_router(diagnostics.router)

    return app


def _explain_permission_error(exc: PermissionError) -> str:
    return (
        f"\nPermission denied: {exc.filename}\n\n"
        "The default paths this app uses (/var/lib/sandia, /etc/dhcp/dhcpd.conf,\n"
        "/var/backups/sandia, ...) need root to write. Pick one:\n\n"
        "  1. Try it with no special access at all, using synthetic data:\n"
        "       sandia --dummy\n\n"
        "  2. Point it at somewhere you can write, e.g.:\n"
        "       SANDIA_DATA_DIR=$HOME/.local/share/sandia sandia\n\n"
        "  3. Run it with sudo to manage the real dhcpd.conf and service:\n"
        "       sudo .venv/bin/sandia\n\n"
        "See INSTRUCTIONS.md for details."
    )


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sandia", description="Web UI for managing an ISC isc-dhcp-server instance.")
    parser.add_argument(
        "--dummy",
        action="store_true",
        help="Run with synthetic demo data instead of a real dhcpd.conf/leases file - no root or sudo required. Testing only.",
    )
    parser.add_argument(
        "--set-password",
        metavar="USERNAME",
        help="Set an existing user's password (prompts for it) and exit, without starting the server. "
        "Useful to change or recover the admin password by editing the database directly.",
    )
    parser.add_argument("--version", action="version", version=f"sandia {__version__}")
    return parser


def _run_set_password(username: str, settings: Settings) -> None:
    import getpass
    import sys

    try:
        engine = create_db_engine(settings)
    except PermissionError as exc:
        print(_explain_permission_error(exc), file=sys.stderr)
        sys.exit(1)

    with Session(engine) as session:
        user = session.exec(select(User).where(User.username == username)).first()
        if user is None:
            print(f"No such user: {username!r}", file=sys.stderr)
            sys.exit(1)

        password = getpass.getpass("New password: ")
        confirm = getpass.getpass("Confirm password: ")
        if not password:
            print("Password cannot be empty.", file=sys.stderr)
            sys.exit(1)
        if password != confirm:
            print("Passwords did not match.", file=sys.stderr)
            sys.exit(1)

        user.password_hash = hash_password(password)
        session.add(user)
        session.commit()

    print(f"Password updated for {username!r}.")


def run(argv: list[str] | None = None) -> None:
    import sys

    import uvicorn

    args = _build_arg_parser().parse_args(argv)
    if args.dummy:
        os.environ["SANDIA_DUMMY_DATA"] = "1"

    settings = Settings()

    if args.set_password:
        _run_set_password(args.set_password, settings)
        return

    try:
        app = create_app(settings)
    except PermissionError as exc:
        print(_explain_permission_error(exc), file=sys.stderr)
        sys.exit(1)

    if settings.dummy_data:
        print(f"Dummy data mode (--dummy / SANDIA_DUMMY_DATA=1) - using synthetic config at {settings.dhcpd_conf_path}")

    ssl_kwargs = {}
    if settings.enable_https:
        try:
            cert_path, key_path = ensure_self_signed_cert(settings.tls_dir)
        except PermissionError as exc:
            print(_explain_permission_error(exc), file=sys.stderr)
            sys.exit(1)
        ssl_kwargs = {"ssl_certfile": str(cert_path), "ssl_keyfile": str(key_path)}
        print(f"HTTPS enabled - serving on https://{settings.host}:{settings.port}")
    else:
        print(f"HTTPS disabled (SANDIA_HTTPS=0) - serving on http://{settings.host}:{settings.port}")

    uvicorn.run(app, host=settings.host, port=settings.port, **ssl_kwargs)
