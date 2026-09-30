from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session

from ..audit import log_action
from ..config import Settings, get_settings
from ..db import get_session
from ..dhcpd import apply as apply_module
from ..i18n import _
from ..models import User
from ..rendering import render, set_flash
from ..security import require_login, require_role

router = APIRouter()


@router.get("/service")
async def service_page(
    request: Request,
    user: User = Depends(require_login),
    settings: Settings = Depends(get_settings),
):
    status = await apply_module.service_status(settings)
    enabled = await apply_module.service_is_enabled(settings)
    return render(request, "service/index.html", user=user, status=status, enabled=enabled, service_name=settings.service_name)


@router.get("/service/status")
async def service_status_partial(
    request: Request,
    user: User = Depends(require_login),
    settings: Settings = Depends(get_settings),
):
    status = await apply_module.service_status(settings)
    enabled = await apply_module.service_is_enabled(settings)
    return render(request, "service/_status.html", user=user, status=status, enabled=enabled)


@router.post("/service/restart")
async def restart(
    request: Request,
    user: User = Depends(require_role("operator")),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    result = await apply_module.restart_service(settings)
    log_action(session, request, user, "service_restart", result.stdout or result.stderr, success=result.ok)
    set_flash(request, _("Service restarted.") if result.ok else _("Restart failed: {error}", error=result.stderr), kind="success" if result.ok else "error")
    return RedirectResponse("/service", status_code=303)


@router.post("/service/enable")
async def enable(
    request: Request,
    user: User = Depends(require_role("admin")),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    result = await apply_module.enable_service(settings)
    log_action(session, request, user, "service_enable", result.stdout or result.stderr, success=result.ok)
    set_flash(request, _("Service enabled at boot.") if result.ok else _("Enable failed: {error}", error=result.stderr), kind="success" if result.ok else "error")
    return RedirectResponse("/service", status_code=303)


@router.post("/service/disable")
async def disable(
    request: Request,
    user: User = Depends(require_role("admin")),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    result = await apply_module.disable_service(settings)
    log_action(session, request, user, "service_disable", result.stdout or result.stderr, success=result.ok)
    set_flash(request, _("Service disabled at boot.") if result.ok else _("Disable failed: {error}", error=result.stderr), kind="success" if result.ok else "error")
    return RedirectResponse("/service", status_code=303)
