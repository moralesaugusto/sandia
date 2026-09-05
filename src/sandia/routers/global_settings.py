from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session

from ..audit import log_action
from ..config import Settings, get_settings
from ..config_store import load_live_config
from ..db import get_session
from ..dhcpd import Parameter, serialize
from ..dhcpd.apply import apply_new_config
from ..models import User
from ..rendering import render, set_flash
from ..security import require_role

router = APIRouter()


def _fields_from_config(config) -> dict:
    return {
        "authoritative": config.get("authoritative") is not None,
        "default_lease_time": config.get("default-lease-time") or "",
        "max_lease_time": config.get("max-lease-time") or "",
        "domain_name": (config.get("domain-name") or "").strip('"'),
        "domain_name_servers": config.get("domain-name-servers") or "",
        "ntp_servers": config.get("ntp-servers") or "",
    }


@router.get("/settings")
async def settings_form(
    request: Request,
    user: User = Depends(require_role("operator")),
    settings: Settings = Depends(get_settings),
):
    config = load_live_config(settings)
    return render(request, "settings/form.html", user=user, fields=_fields_from_config(config))


@router.post("/settings")
async def settings_submit(
    request: Request,
    user: User = Depends(require_role("operator")),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    authoritative: bool = Form(False),
    default_lease_time: str = Form(""),
    max_lease_time: str = Form(""),
    domain_name: str = Form(""),
    domain_name_servers: str = Form(""),
    ntp_servers: str = Form(""),
):
    config = load_live_config(settings)

    config.nodes = [n for n in config.nodes if not (hasattr(n, "name") and n.name == "authoritative")]
    if authoritative:
        config.nodes.insert(0, Parameter("authoritative", ""))

    if default_lease_time:
        config.set("default-lease-time", default_lease_time)
    if max_lease_time:
        config.set("max-lease-time", max_lease_time)
    if domain_name:
        config.set("domain-name", f'"{domain_name}"', as_option=True)
    if domain_name_servers:
        config.set("domain-name-servers", domain_name_servers, as_option=True)
    if ntp_servers:
        config.set("ntp-servers", ntp_servers, as_option=True)

    result = await apply_new_config(settings, serialize(config))
    if not result.ok:
        log_action(session, request, user, "global_settings_update_failed", result.output, success=False)
        set_flash(request, f"Validation failed ({result.stage}): {result.output}", kind="error")
        return RedirectResponse("/settings", status_code=303)

    log_action(session, request, user, "global_settings_update", "updated global DHCP settings")
    set_flash(request, "Global settings applied. Restart isc-dhcp-server to take effect.")
    return RedirectResponse("/settings", status_code=303)
