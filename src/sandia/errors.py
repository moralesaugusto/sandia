from fastapi import FastAPI, Request
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import PlainTextResponse


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(request: Request, exc: StarletteHTTPException):
        if 300 <= exc.status_code < 400:
            # Redirects (e.g. "not logged in") - preserve Location, no error chrome.
            return PlainTextResponse(exc.detail or "", status_code=exc.status_code, headers=exc.headers)

        templates = request.app.state.templates
        if request.headers.get("HX-Request") == "true":
            return templates.TemplateResponse(
                request, "partials/_error.html", {"detail": exc.detail}, status_code=exc.status_code
            )
        return templates.TemplateResponse(
            request,
            "error.html",
            {"detail": exc.detail, "status_code": exc.status_code, "user": None},
            status_code=exc.status_code,
        )
