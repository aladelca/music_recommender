from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from music_recommender import __version__
from music_recommender.api.errors import register_error_handlers
from music_recommender.api.models import HealthResponse, ReadinessResponse
from music_recommender.api.observability_middleware import ProductObservabilityMiddleware
from music_recommender.api.product_runtime import ProductAuthRuntime, build_product_auth_runtime
from music_recommender.api.routes import (
    auth,
    discovery,
    evaluations,
    feedback,
    music,
    playlists,
    recommendations,
)


def create_product_app(*, runtime: ProductAuthRuntime | Any | None = None) -> FastAPI:
    resolved_runtime = runtime or build_product_auth_runtime()
    api = FastAPI(
        title="Outside the Loop API",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    api.state.auth_mode = "spotify_session"
    api.state.product_database = resolved_runtime.database
    api.state.product_auth_service = resolved_runtime.auth_service
    api.state.session_service = resolved_runtime.session_service
    api.state.csrf_protection = resolved_runtime.csrf_protection
    api.state.seed_service = resolved_runtime.seed_service
    api.state.discovery_job_service = resolved_runtime.discovery_job_service
    api.state.recommendation_service = resolved_runtime.recommendation_service
    api.state.playlist_export_service = resolved_runtime.playlist_export_service
    api.state.feedback_evaluation_service = resolved_runtime.feedback_evaluation_service
    api.state.account_service = resolved_runtime.account_service
    api.state.readiness_probe = resolved_runtime.ready
    api.add_middleware(ProductObservabilityMiddleware, observer=resolved_runtime.observer)
    register_error_handlers(api)

    @api.get("/health", response_model=HealthResponse, tags=["system"])
    def health() -> HealthResponse:
        return HealthResponse(status="ok", version=__version__)

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
    api.include_router(recommendations.product_router)
    api.include_router(playlists.product_router)
    api.include_router(feedback.product_router)
    return api
