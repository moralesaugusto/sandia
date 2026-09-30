from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session

from ..audit import log_action
from ..config import Settings, get_settings
from ..db import get_session
from ..i18n import DEFAULT_LANGUAGE, LANGUAGES, _
from ..models import User, utcnow
from ..rate_limit import clear_failures, record_failure, seconds_locked
from ..rendering import render, set_flash
from ..security import find_user, hash_password, require_login, verify_password

router = APIRouter()

THEMES = ("dark", "light")


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
        set_flash(request, _("Too many failed attempts. Try again in {value}s.", value=int(remaining) + 1), kind="error")
        return render(request, "login.html", status_code=429)

    user = find_user(session, username)
    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        record_failure(rate_key)
        log_action(session, request, user, "login_failed", f"username={username}", success=False)
        set_flash(request, _("Invalid username or password."), kind="error")
        return render(request, "login.html", status_code=401)

    clear_failures(rate_key)
    request.session["user_id"] = user.id
    # Only seed from the account's saved preference if this browser hasn't
    # already picked one on the login page - never clobber a choice just made.
    request.session.setdefault("theme", user.theme)
    request.session.setdefault("lang", user.language)
    user.last_login = utcnow()
    session.add(user)
    session.commit()
    log_action(session, request, user, "login", "")
    return RedirectResponse("/", status_code=303)


@router.post("/logout")
def logout(request: Request, session: Session = Depends(get_session)):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@router.post("/account/theme")
def set_theme(
    request: Request,
    theme: str = Form(...),
    next: str = Form("/"),
    session: Session = Depends(get_session),
):
    if theme not in THEMES:
        theme = "dark"
    request.session["theme"] = theme
    user_id = request.session.get("user_id")
    if user_id is not None:
        user = session.get(User, user_id)
        if user is not None:
            user.theme = theme
            session.add(user)
            session.commit()
    if not next.startswith("/"):
        next = "/"
    return RedirectResponse(next, status_code=303)


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
        set_flash(request, _("Current password is incorrect."), kind="error")
        return RedirectResponse("/account/password", status_code=303)
    if not new_password:
        set_flash(request, _("New password cannot be empty."), kind="error")
        return RedirectResponse("/account/password", status_code=303)
    if new_password != confirm_password:
        set_flash(request, _("New passwords do not match."), kind="error")
        return RedirectResponse("/account/password", status_code=303)

    user.password_hash = hash_password(new_password)
    session.add(user)
    session.commit()
    log_action(session, request, user, "password_change", "self-service password change")
    set_flash(request, _("Password updated."))
    return RedirectResponse("/account/password", status_code=303)


@router.post("/account/language")
def set_language(
    request: Request,
    lang: str = Form(...),
    next: str = Form("/"),
    session: Session = Depends(get_session),
):
    if lang not in LANGUAGES:
        lang = DEFAULT_LANGUAGE
    request.session["lang"] = lang
    user_id = request.session.get("user_id")
    if user_id is not None:
        user = session.get(User, user_id)
        if user is not None:
            user.language = lang
            session.add(user)
            session.commit()
    if not next.startswith("/") or next.startswith("//"):
        next = "/"
    return RedirectResponse(next, status_code=303)
