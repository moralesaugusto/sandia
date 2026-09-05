from fastapi import Request
from sqlmodel import Session

from .models import AuditLog, User


def log_action(session: Session, request: Request, user: User | None, action: str, detail: str, success: bool = True) -> None:
    entry = AuditLog(
        username=user.username if user else "anonymous",
        action=action,
        detail=detail,
        success=success,
        ip_address=request.client.host if request.client else "unknown",
    )
    session.add(entry)
    session.commit()
