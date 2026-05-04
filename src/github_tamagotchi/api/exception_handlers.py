"""FastAPI exception handlers for domain exceptions."""

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from fastapi.templating import Jinja2Templates

from github_tamagotchi.core import bugbarn as bb
from github_tamagotchi.exceptions import ConflictError, NotFoundError, RepositoryError

logger = structlog.get_logger()


def _wants_html(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    return "text/html" in accept


def _error_html(
    request: Request, templates: Jinja2Templates | None, status_code: int, message: str
) -> Response:
    if templates:
        return templates.TemplateResponse(
            request,
            "error.html",
            {"status_code": status_code, "message": message},
            status_code=status_code,
        )
    return JSONResponse(status_code=status_code, content={"detail": message})


def register_exception_handlers(
    app: FastAPI, templates: Jinja2Templates | None = None
) -> None:
    """Register domain exception → HTTP status handlers on *app*."""

    @app.exception_handler(NotFoundError)
    async def not_found_handler(request: Request, exc: NotFoundError) -> Response:
        if _wants_html(request):
            return _error_html(request, templates, 404, str(exc))
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(ConflictError)
    async def conflict_handler(request: Request, exc: ConflictError) -> Response:
        if _wants_html(request):
            return _error_html(request, templates, 409, str(exc))
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(RepositoryError)
    async def repository_error_handler(request: Request, exc: RepositoryError) -> Response:
        logger.error("repository_error", path=request.url.path, error=str(exc), exc_info=exc)
        bb.capture_error(exc)
        if _wants_html(request):
            return _error_html(request, templates, 500, "Something went wrong")
        return JSONResponse(status_code=500, content={"detail": "Internal error"})

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> Response:
        if _wants_html(request) and exc.status_code >= 400:
            msg = exc.detail or "An error occurred"
            return _error_html(request, templates, exc.status_code, msg)
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> Response:
        logger.error("unhandled_exception", path=request.url.path, error=str(exc), exc_info=exc)
        bb.capture_error(exc)
        if _wants_html(request):
            return _error_html(request, templates, 500, "Something went wrong")
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})
