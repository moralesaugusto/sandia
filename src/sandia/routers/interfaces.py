import shutil
from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session

from ..audit import log_action
from ..config import Settings, get_settings
from ..config_store import load_live_config
from ..db import get_session
from ..dhcpd import kea
from ..dhcpd.apply import apply_new_config
from ..dhcpd.backend import get_backend, live_config_text
from ..dhcpd.parser import ParseError
from ..dhcpd.subnet_interface import get_subnet_interface
from ..i18n import _
from ..interfaces_conf import read_configured_interfaces, set_interfaces
from ..models import User
from ..rendering import render, set_flash
from ..security import require_login, require_role

router = APIRouter()


def _read(path) -> str:
    return path.read_text() if path.exists() else ""


@router.get("/interfaces")
async def interfaces_page(
    request: Request,
    user: User = Depends(require_login),
    settings: Settings = Depends(get_settings),
):
    backend = get_backend(settings)
    config_error = None
    if backend.name == "kea":
        conf_path = settings.dhcpd_conf_path
        try:
            interfaces = kea.configured_interfaces(live_config_text(settings) or "{}")
        except ParseError as exc:
            interfaces, config_error = [], str(exc)
    else:
        conf_path = settings.interfaces_conf_path
        interfaces = read_configured_interfaces(conf_path)

    config = load_live_config(settings) if config_error is None else None
    subnet_interfaces = [
        {"subnet": subnet, "interface": get_subnet_interface(config, subnet)} for subnet in (config.subnets if config else [])
    ]
    # Kea entries may be "eth0/192.0.2.1" or "*" (every interface).
    listening = {name.split("/")[0] for name in interfaces}

    return render(
        request,
        "interfaces/index.html",
        user=user,
        interfaces=interfaces,
        listening=listening,
        config_error=config_error,
        conf_path=str(conf_path),
        file_exists=conf_path.exists(),
        subnet_interfaces=subnet_interfaces,
    )


@router.post("/interfaces")
async def update_interfaces(
    request: Request,
    user: User = Depends(require_role("operator")),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    interfaces: str = Form(""),
):
    names = [name.strip() for name in interfaces.replace(",", " ").split() if name.strip()]

    if get_backend(settings).name == "kea":
        # Part of kea-dhcp4.conf itself, so it goes through validate/apply.
        try:
            new_text = kea.set_kea_interfaces(live_config_text(settings) or "", names)
        except ParseError as exc:
            set_flash(request, _("Failed to update interfaces: {exc}", exc=exc), kind="error")
            return RedirectResponse("/interfaces", status_code=303)
        result = await apply_new_config(settings, new_text)
        if not result.ok:
            log_action(session, request, user, "interfaces_update_failed", result.output, success=False)
            set_flash(request, _("Apply failed ({stage}): {output}", stage=result.stage, output=result.output), kind="error")
            return RedirectResponse("/interfaces", status_code=303)
        log_action(session, request, user, "interfaces_update", ", ".join(names) or "(none)")
        set_flash(request, _("Interfaces updated. Configuration applied."))
        return RedirectResponse("/interfaces", status_code=303)

    new_text = set_interfaces(_read(settings.interfaces_conf_path), names)
    try:
        settings.interfaces_conf_path.parent.mkdir(parents=True, exist_ok=True)
        if settings.interfaces_conf_path.exists():
            settings.backup_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S%f")
            shutil.copyfile(
                settings.interfaces_conf_path,
                settings.backup_dir / f"isc-dhcp-server-defaults.{stamp}",
            )
        settings.interfaces_conf_path.write_text(new_text)
    except OSError as exc:
        log_action(session, request, user, "interfaces_update_failed", str(exc), success=False)
        set_flash(request, _("Failed to update interfaces: {exc}", exc=exc), kind="error")
        return RedirectResponse("/interfaces", status_code=303)

    log_action(session, request, user, "interfaces_update", ", ".join(names) or "(none)")
    set_flash(request, _("Interfaces updated. Restart isc-dhcp-server to take effect."))
    return RedirectResponse("/interfaces", status_code=303)
