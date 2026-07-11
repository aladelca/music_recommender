from __future__ import annotations

import hmac
import os
from collections.abc import Callable
from typing import Any, Literal, cast

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from music_recommender import __version__
from music_recommender.api.errors import register_error_handlers
from music_recommender.api.models import HealthResponse, ReadinessResponse
from music_recommender.api.product_runtime import build_product_auth_runtime
from music_recommender.api.routes import (
    auth,
    discovery,
    evaluations,
    feedback,
    music,
    playlists,
    profile,
    recommendations,
)
from music_recommender.api.services import DemoApiService
from music_recommender.auth.oauth import ProductAuthService
from music_recommender.auth.sessions import CsrfProtection, SessionService

AuthMode = Literal["api_key", "hybrid", "spotify_session"]
_PUBLIC_PATHS = {"/health", "/ready", "/docs", "/redoc", "/openapi.json"}
_AUTH_PREFIX = "/auth/"
_PRODUCT_SESSION_PREFIXES = ("/discovery/", "/music/", "/me/")


def create_app(
    *,
    load_env: bool = True,
    service: Any | None = None,
    auth_mode: str | None = None,
    product_auth_service: ProductAuthService | Any | None = None,
    session_service: SessionService | None = None,
    csrf_protection: CsrfProtection | None = None,
    seed_service: Any | None = None,
    discovery_job_service: Any | None = None,
    recommendation_service: Any | None = None,
    playlist_export_service: Any | None = None,
    feedback_evaluation_service: Any | None = None,
    account_service: Any | None = None,
    readiness_probe: Callable[[], bool] | None = None,
) -> FastAPI:
    if load_env:
        load_dotenv(".env")

    api = FastAPI(
        title="Music Recommender API",
        version=__version__,
        docs_url="/docs",
        redoc_url="/redoc",
    )
    resolved_auth_mode = _auth_mode(auth_mode)
    if resolved_auth_mode != "api_key" and (
        product_auth_service is None or session_service is None or csrf_protection is None
    ):
        if any(
            dependency is not None
            for dependency in (product_auth_service, session_service, csrf_protection)
        ):
            raise ValueError("Product authentication dependencies must be provided together.")
        runtime = build_product_auth_runtime()
        product_auth_service = runtime.auth_service
        session_service = runtime.session_service
        csrf_protection = runtime.csrf_protection
        readiness_probe = readiness_probe or runtime.ready
        api.state.product_database = runtime.database
        seed_service = runtime.seed_service
        discovery_job_service = runtime.discovery_job_service
        recommendation_service = runtime.recommendation_service
        playlist_export_service = runtime.playlist_export_service
        feedback_evaluation_service = runtime.feedback_evaluation_service
        account_service = runtime.account_service

    api.state.api_service = service or DemoApiService()
    api.state.auth_mode = resolved_auth_mode
    api.state.product_auth_service = product_auth_service
    api.state.session_service = session_service
    api.state.csrf_protection = csrf_protection
    api.state.seed_service = seed_service
    api.state.discovery_job_service = discovery_job_service
    api.state.recommendation_service = recommendation_service
    api.state.playlist_export_service = playlist_export_service
    api.state.feedback_evaluation_service = feedback_evaluation_service
    api.state.account_service = account_service
    api.state.readiness_probe = readiness_probe or (lambda: True)
    register_error_handlers(api)

    @api.middleware("http")
    async def require_api_key(request: Request, call_next: Any) -> Any:
        mode = cast(AuthMode, request.app.state.auth_mode)
        path = request.url.path
        if path.startswith(_AUTH_PREFIX):
            if mode == "api_key":
                return JSONResponse(
                    status_code=404,
                    content={"detail": "Route is disabled.", "code": "route_disabled"},
                )
            return await call_next(request)
        if path.startswith(_PRODUCT_SESSION_PREFIXES):
            return await call_next(request)
        if mode == "spotify_session" and path not in _PUBLIC_PATHS:
            return JSONResponse(
                status_code=404,
                content={"detail": "Route is disabled.", "code": "route_disabled"},
            )
        expected_api_key = os.getenv("RECOMMENDER_API_KEY", "").strip()
        if expected_api_key and path not in _PUBLIC_PATHS:
            provided_api_key = request.headers.get("x-api-key", "")
            if not hmac.compare_digest(provided_api_key, expected_api_key):
                return JSONResponse(status_code=401, content={"detail": "Invalid API key."})
        return await call_next(request)

    @api.get("/health", response_model=HealthResponse, tags=["system"])
    def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            version=__version__,
        )

    @api.get("/ready", response_model=ReadinessResponse, tags=["system"])
    def ready() -> ReadinessResponse | JSONResponse:
        try:
            is_ready = bool(api.state.readiness_probe())
        except Exception:
            is_ready = False
        if is_ready:
            return ReadinessResponse(status="ready")
        return JSONResponse(status_code=503, content={"status": "unavailable"})

    api.include_router(auth.router)
    api.include_router(discovery.router)
    api.include_router(evaluations.router)
    api.include_router(music.router)
    api.include_router(recommendations.router)
    api.include_router(recommendations.product_router)
    api.include_router(playlists.router)
    api.include_router(playlists.product_router)
    api.include_router(feedback.router)
    api.include_router(feedback.product_router)
    api.include_router(profile.router)
    return api


def _auth_mode(value: str | None) -> AuthMode:
    raw_value = value if value is not None else (os.getenv("AUTH_MODE") or "api_key")
    normalized = raw_value.strip().lower()
    if normalized not in {"api_key", "hybrid", "spotify_session"}:
        raise ValueError("AUTH_MODE must be one of: api_key, hybrid, spotify_session")
    return cast(AuthMode, normalized)


app = create_app()
