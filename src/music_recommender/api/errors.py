from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class ApiConfigurationError(RuntimeError):
    pass


class ApiValidationError(ValueError):
    pass


class ApiNotFoundError(LookupError):
    pass


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiValidationError)
    def validation_error_handler(
        request: Request,
        exc: ApiValidationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={"detail": str(exc)},
        )

    @app.exception_handler(ApiNotFoundError)
    def not_found_error_handler(
        request: Request,
        exc: ApiNotFoundError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"detail": str(exc)},
        )

    @app.exception_handler(ApiConfigurationError)
    def configuration_error_handler(
        request: Request,
        exc: ApiConfigurationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={"detail": str(exc)},
        )
