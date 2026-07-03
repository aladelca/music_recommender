from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class ApiConfigurationError(RuntimeError):
    pass


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiConfigurationError)
    def configuration_error_handler(
        request: Request,
        exc: ApiConfigurationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={"detail": str(exc)},
        )
