from fastapi import Request
from fastapi.responses import HTMLResponse


def render(request: Request, template_name: str, status_code: int = 200, **context) -> HTMLResponse:
    templates = request.app.state.templates
    context.setdefault("user", None)
    context["flash"] = request.session.pop("flash", None)
    return templates.TemplateResponse(request, template_name, context, status_code=status_code)


def set_flash(request: Request, message: str, kind: str = "success") -> None:
    request.session["flash"] = {"message": message, "kind": kind}
