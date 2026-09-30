from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Depends, HTTPException, Request, status
from sqlmodel import Session, select

from .db import get_session
from .i18n import _
from .models import User

_hasher = PasswordHasher()

ROLES = ("admin", "operator", "viewer")
ROLE_RANK = {role: rank for rank, role in enumerate(ROLES[::-1])}  # viewer=0, operator=1, admin=2


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def get_current_user(request: Request, session: Session = Depends(get_session)) -> User | None:
    user_id = request.session.get("user_id")
    if user_id is None:
        return None
    user = session.get(User, user_id)
    if user is None or not user.is_active:
        return None
    return user


def require_login(request: Request, session: Session = Depends(get_session)) -> User:
    user = get_current_user(request, session)
    if user is None:
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/login"})
    return user


def require_role(*roles: str):
    minimum_rank = min(ROLE_RANK[r] for r in roles)

    def dependency(user: User = Depends(require_login)) -> User:
        if ROLE_RANK[user.role] < minimum_rank:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_("insufficient role"))
        return user

    return dependency


def find_user(session: Session, username: str) -> User | None:
    return session.exec(select(User).where(User.username == username)).first()
