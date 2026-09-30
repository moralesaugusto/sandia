from fastapi import Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session

from .ai import load_ai_settings


def render(request: Request, template_name: str, status_code: int = 200, **context) -> HTMLResponse:
    templates = request.app.state.templates
    context.setdefault("user", None)
    context.setdefault("theme", request.session.get("theme", "dark"))
    if context["user"] is not None:
        # Drives the floating assistant in base.html.
        with Session(request.app.state.engine) as session:
            context["ai_enabled"] = load_ai_settings(session).configured
    context["flash"] = request.session.pop("flash", None)
    return templates.TemplateResponse(request, template_name, context, status_code=status_code)


def set_flash(request: Request, message: str, kind: str = "success") -> None:
    request.session["flash"] = {"message": message, "kind": kind}
