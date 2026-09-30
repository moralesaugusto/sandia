from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session

from ..audit import log_action
from ..config import Settings, get_settings
from ..db import get_session
from ..dhcpd.apply import apply_new_config
from ..i18n import _
from ..models import User
from ..rendering import render, set_flash
from ..security import require_login, require_role

router = APIRouter()


@router.get("/backups")
async def list_backups(
    request: Request,
    user: User = Depends(require_login),
    settings: Settings = Depends(get_settings),
):
    names = []
    if settings.backup_dir.exists():
        names = sorted((p.name for p in settings.backup_dir.glob("dhcpd.conf.*")), reverse=True)
    return render(request, "backups/list.html", user=user, backups=names)


@router.post("/backups/{filename}/restore")
async def restore_backup(
    filename: str,
    request: Request,
    user: User = Depends(require_role("operator")),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    path = settings.backup_dir / filename
    if "/" in filename or not path.is_file():
        set_flash(request, _("Backup file not found."), kind="error")
        return RedirectResponse("/backups", status_code=303)

    result = await apply_new_config(settings, path.read_text())
    if not result.ok:
        log_action(session, request, user, "backup_restore_failed", result.output, success=False)
        set_flash(request, _("Restore failed ({stage}): {output}", stage=result.stage, output=result.output), kind="error")
        return RedirectResponse("/backups", status_code=303)

    log_action(session, request, user, "backup_restore", filename)
    set_flash(request, _("Backup restored (a fresh backup of the prior config was taken first). isc-dhcp-server restarted."))
    return RedirectResponse("/backups", status_code=303)
