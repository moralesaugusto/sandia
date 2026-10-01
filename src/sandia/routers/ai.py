import httpx
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import PlainTextResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel
from sqlmodel import Session

from ..ai import (
    build_context,
    chat_stream,
    clean_history,
    list_models,
    load_ai_settings,
    normalize_ollama_url,
    system_prompt,
)
from ..audit import log_action
from ..config import Settings, get_settings
from ..db import get_session
from ..dhcpd.backend import get_backend
from ..i18n import _
from ..models import User
from ..rendering import render, set_flash
from ..security import require_login, require_role

router = APIRouter()


class ChatRequest(BaseModel):
    messages: list


@router.get("/settings/ai")
async def ai_settings_form(
    request: Request,
    user: User = Depends(require_role("admin")),
    session: Session = Depends(get_session),
):
    return render(request, "settings/ai.html", user=user, ai=load_ai_settings(session))


@router.post("/settings/ai")
async def ai_settings_submit(
    request: Request,
    user: User = Depends(require_role("admin")),
    session: Session = Depends(get_session),
    ollama_url: str = Form(""),
    model: str = Form(""),
):
    try:
        url = normalize_ollama_url(ollama_url)
    except ValueError as exc:
        set_flash(request, str(exc), kind="error")
        return RedirectResponse("/settings/ai", status_code=303)

    ai = load_ai_settings(session)
    ai.ollama_url = url
    ai.model = model.strip()
    session.add(ai)
    session.commit()

    log_action(session, request, user, "ai_settings_update", f"ollama_url={ai.ollama_url or '-'} model={ai.model or '-'}")
    set_flash(request, _("AI settings saved.") if ai.configured else _("AI settings saved. The assistant stays off until both a server and a model are set."))
    return RedirectResponse("/settings/ai", status_code=303)


@router.get("/settings/ai/models")
async def ai_models(
    request: Request,
    user: User = Depends(require_role("admin")),
    ollama_url: str = "",
):
    models, error = [], None
    try:
        url = normalize_ollama_url(ollama_url)
        if not url:
            error = _("Enter the Ollama server address first.")
        else:
            models = await list_models(url)
            if not models:
                error = _("Ollama at {url} has no models installed (run 'ollama pull <model>' on that host).", url=url)
    except ValueError as exc:
        error = str(exc)
    except httpx.HTTPError as exc:
        error = _("Could not reach Ollama at {url}: {error}", url=url, error=f"{type(exc).__name__}: {exc}")
    return render(request, "settings/_ai_models.html", user=user, models=models, error=error)


@router.post("/ai/chat")
async def ai_chat(
    body: ChatRequest,
    user: User = Depends(require_login),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    ai = load_ai_settings(session)
    if not ai.configured:
        return PlainTextResponse(_("The AI assistant is not configured. An admin can set it up under Advanced Settings > AI Settings."), status_code=409)

    history = clean_history(body.messages)
    if not history:
        return PlainTextResponse(_("No question to answer."), status_code=400)

    context = await build_context(settings)
    messages = [{"role": "system", "content": f"{system_prompt(get_backend(settings).label)}\n\n{context}"}, *history]
    return StreamingResponse(chat_stream(ai.ollama_url, ai.model, messages), media_type="text/plain; charset=utf-8")
