from __future__ import annotations

import hmac
import os
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from music_recommender import __version__
from music_recommender.api.errors import register_error_handlers
from music_recommender.api.models import ConfigPresence, HealthResponse
from music_recommender.api.routes import feedback, playlists, profile, recommendations
from music_recommender.api.services import DemoApiService

_API_KEY_EXEMPT_PATHS = {"/health", "/docs", "/redoc", "/openapi.json"}


def create_app(*, load_env: bool = True, service: Any | None = None) -> FastAPI:
    if load_env:
        load_dotenv(".env")

    api = FastAPI(
        title="Music Recommender API",
        version=__version__,
        docs_url="/docs",
        redoc_url="/redoc",
    )
    api.state.api_service = service or DemoApiService()
    register_error_handlers(api)

    @api.middleware("http")
    async def require_api_key(request: Request, call_next: Any) -> Any:
        expected_api_key = os.getenv("RECOMMENDER_API_KEY", "").strip()
        if expected_api_key and request.url.path not in _API_KEY_EXEMPT_PATHS:
            provided_api_key = request.headers.get("x-api-key", "")
            if not hmac.compare_digest(provided_api_key, expected_api_key):
                return JSONResponse(status_code=401, content={"detail": "Invalid API key."})
        return await call_next(request)

    @api.get("/health", response_model=HealthResponse, tags=["system"])
    def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            version=__version__,
            config=_config_presence(),
        )

    api.include_router(recommendations.router)
    api.include_router(playlists.router)
    api.include_router(feedback.router)
    api.include_router(profile.router)
    return api


def _config_presence() -> ConfigPresence:
    return ConfigPresence(
        aws_region=os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1",
        api_key_required=_has_value("RECOMMENDER_API_KEY"),
        aws_secrets_prefix_present=_has_value("AWS_SECRETS_PREFIX"),
        music_recommender_bucket_present=_has_value("MUSIC_RECOMMENDER_BUCKET"),
        openai_api_key_present=_has_value("OPENAI_API_KEY"),
        recommender_data_mode=os.getenv("RECOMMENDER_DATA_MODE", "local"),
        recommender_data_root_present=_has_value("RECOMMENDER_DATA_ROOT"),
        spotify_client_id_present=_has_value("SPOTIFY_APP_CLIENT_ID", "SPOTIFY_CLIENT_ID"),
        spotify_client_secret_present=_has_value(
            "SPOTIFY_APP_CLIENT_SECRET",
            "SPOTIFY_CLIENT_SECRET",
        ),
        spotify_user_refresh_token_present=_has_value("SPOTIFY_USER_REFRESH_TOKEN"),
    )


def _has_value(*names: str) -> bool:
    return any(bool(os.getenv(name, "").strip()) for name in names)


app = create_app()
