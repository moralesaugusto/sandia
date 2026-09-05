from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session

from ..audit import log_action
from ..config import Settings, get_settings
from ..db import get_session
from ..models import User, utcnow
from ..rate_limit import clear_failures, record_failure, seconds_locked
from ..rendering import render, set_flash
from ..security import find_user, hash_password, require_login, verify_password

router = APIRouter()


@router.get("/login")
def login_form(request: Request):
    if request.session.get("user_id"):
        return RedirectResponse("/", status_code=303)
    return render(request, "login.html")


@router.post("/login")
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    rate_key = username.strip().lower()
    remaining = seconds_locked(rate_key)
    if remaining > 0:
        set_flash(request, f"Too many failed attempts. Try again in {int(remaining) + 1}s.", kind="error")
        return render(request, "login.html", status_code=429)

    user = find_user(session, username)
    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        record_failure(rate_key)
        log_action(session, request, user, "login_failed", f"username={username}", success=False)
        set_flash(request, "Invalid username or password.", kind="error")
        return render(request, "login.html", status_code=401)

    clear_failures(rate_key)
    request.session["user_id"] = user.id
    user.last_login = utcnow()
    session.add(user)
    session.commit()
    log_action(session, request, user, "login", "")
    return RedirectResponse("/", status_code=303)


@router.post("/logout")
def logout(request: Request, session: Session = Depends(get_session)):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@router.get("/account/password")
def change_password_form(request: Request, user: User = Depends(require_login)):
    return render(request, "account/change_password.html", user=user)


@router.post("/account/password")
def change_password_submit(
    request: Request,
    user: User = Depends(require_login),
    session: Session = Depends(get_session),
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
):
    if not verify_password(current_password, user.password_hash):
        set_flash(request, "Current password is incorrect.", kind="error")
        return RedirectResponse("/account/password", status_code=303)
    if not new_password:
        set_flash(request, "New password cannot be empty.", kind="error")
        return RedirectResponse("/account/password", status_code=303)
    if new_password != confirm_password:
        set_flash(request, "New passwords do not match.", kind="error")
        return RedirectResponse("/account/password", status_code=303)

    user.password_hash = hash_password(new_password)
    session.add(user)
    session.commit()
    log_action(session, request, user, "password_change", "self-service password change")
    set_flash(request, "Password updated.")
    return RedirectResponse("/account/password", status_code=303)
