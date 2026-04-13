"""FastAPI exception handlers for domain exceptions."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from github_tamagotchi.exceptions import ConflictError, NotFoundError, RepositoryError


def register_exception_handlers(app: FastAPI) -> None:
    """Register domain exception → HTTP status handlers on *app*."""

    @app.exception_handler(NotFoundError)
    async def not_found_handler(request: Request, exc: NotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(ConflictError)
    async def conflict_handler(request: Request, exc: ConflictError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(RepositoryError)
    async def repository_error_handler(request: Request, exc: RepositoryError) -> JSONResponse:
        return JSONResponse(status_code=500, content={"detail": "Internal error"})
