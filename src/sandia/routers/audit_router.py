from fastapi import APIRouter, Depends, Request
from sqlmodel import Session, select

from ..db import get_session
from ..models import AuditLog, User
from ..rendering import render
from ..security import require_role

router = APIRouter()


@router.get("/audit")
async def audit_log(
    request: Request,
    user: User = Depends(require_role("operator")),
    session: Session = Depends(get_session),
):
    entries = session.exec(select(AuditLog).order_by(AuditLog.timestamp.desc()).limit(200)).all()
    return render(request, "audit/list.html", user=user, entries=entries)
