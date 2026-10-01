from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

from ..config import Settings, get_settings
from ..dhcpd.backend import get_backend
from ..i18n import _
from ..models import User
from ..pending_changes import propose_change
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
        names = sorted((p.name for p in settings.backup_dir.glob(f"{get_backend(settings).backup_prefix}.*")), reverse=True)
    return render(request, "backups/list.html", user=user, backups=names)


@router.post("/backups/{filename}/restore")
async def restore_backup(
    filename: str,
    request: Request,
    user: User = Depends(require_role("operator")),
    settings: Settings = Depends(get_settings),
):
    path = settings.backup_dir / filename
    if "/" in filename or not path.is_file():
        set_flash(request, _("Backup file not found."), kind="error")
        return RedirectResponse("/backups", status_code=303)

    message = _("Backup restored (a fresh backup of the prior config was taken first). {service} restarted.", service=get_backend(settings).label)
    return propose_change(request, settings, user, path.read_text(), "backup_restore", filename, message, "/backups")
