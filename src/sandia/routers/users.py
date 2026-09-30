from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session, select

from ..audit import log_action
from ..db import get_session
from ..i18n import _
from ..models import User
from ..rendering import render, set_flash
from ..security import ROLES, hash_password, require_role

router = APIRouter()


@router.get("/users")
async def list_users(
    request: Request,
    user: User = Depends(require_role("admin")),
    session: Session = Depends(get_session),
):
    users = session.exec(select(User).order_by(User.username)).all()
    return render(request, "users/list.html", user=user, users=users)


@router.get("/users/new")
async def new_user_form(request: Request, user: User = Depends(require_role("admin"))):
    return render(request, "users/form.html", user=user, target=None, is_new=True, roles=ROLES)


@router.post("/users/new")
async def create_user(
    request: Request,
    user: User = Depends(require_role("admin")),
    session: Session = Depends(get_session),
    username: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),
):
    if role not in ROLES:
        set_flash(request, _("Invalid role."), kind="error")
        return RedirectResponse("/users/new", status_code=303)
    if session.exec(select(User).where(User.username == username)).first() is not None:
        set_flash(request, _("A user with that username already exists."), kind="error")
        return RedirectResponse("/users/new", status_code=303)

    new_user = User(username=username, password_hash=hash_password(password), role=role)
    session.add(new_user)
    session.commit()
    log_action(session, request, user, "user_create", f"{username} ({role})")
    set_flash(request, _("User created."))
    return RedirectResponse("/users", status_code=303)


@router.get("/users/{user_id}/edit")
async def edit_user_form(
    user_id: int,
    request: Request,
    user: User = Depends(require_role("admin")),
    session: Session = Depends(get_session),
):
    target = session.get(User, user_id)
    if target is None:
        set_flash(request, _("User not found."), kind="error")
        return RedirectResponse("/users", status_code=303)
    return render(request, "users/form.html", user=user, target=target, is_new=False, roles=ROLES)


@router.post("/users/{user_id}/edit")
async def update_user(
    user_id: int,
    request: Request,
    user: User = Depends(require_role("admin")),
    session: Session = Depends(get_session),
    role: str = Form(...),
    is_active: bool = Form(False),
    password: str = Form(""),
):
    target = session.get(User, user_id)
    if target is None:
        set_flash(request, _("User not found."), kind="error")
        return RedirectResponse("/users", status_code=303)
    if role not in ROLES:
        set_flash(request, _("Invalid role."), kind="error")
        return RedirectResponse(f"/users/{user_id}/edit", status_code=303)
    if target.id == user.id and (role != "admin" or not is_active):
        set_flash(request, _("You cannot demote or deactivate your own account."), kind="error")
        return RedirectResponse(f"/users/{user_id}/edit", status_code=303)

    target.role = role
    target.is_active = is_active
    if password:
        target.password_hash = hash_password(password)
    session.add(target)
    session.commit()
    log_action(session, request, user, "user_update", target.username)
    set_flash(request, _("User updated."))
    return RedirectResponse("/users", status_code=303)


@router.post("/users/{user_id}/delete")
async def delete_user(
    user_id: int,
    request: Request,
    user: User = Depends(require_role("admin")),
    session: Session = Depends(get_session),
):
    target = session.get(User, user_id)
    if target is None:
        set_flash(request, _("User not found."), kind="error")
        return RedirectResponse("/users", status_code=303)
    if target.id == user.id:
        set_flash(request, _("You cannot delete your own account."), kind="error")
        return RedirectResponse("/users", status_code=303)

    session.delete(target)
    session.commit()
    log_action(session, request, user, "user_delete", target.username)
    set_flash(request, _("User deleted."))
    return RedirectResponse("/users", status_code=303)
