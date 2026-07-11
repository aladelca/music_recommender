from __future__ import annotations

from typing import Annotated, Any, cast

from fastapi import Depends, Request

from music_recommender.api.errors import (
    ApiAccessPendingError,
    ApiAccessRevokedError,
    ApiConfigurationError,
    ApiSpotifyReconnectRequiredError,
)
from music_recommender.auth.models import ProductUser
from music_recommender.auth.oauth import ProductAuthService
from music_recommender.auth.sessions import (
    CSRF_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    CsrfProtection,
    SessionService,
)
from music_recommender.observability import mark_request_account
from music_recommender.product.account_service import AccountService
from music_recommender.product.discovery_service import DiscoveryJobService
from music_recommender.product.feedback_service import FeedbackEvaluationService
from music_recommender.product.playlist_export_service import PlaylistExportService
from music_recommender.product.recommendation_service import RecommendationService
from music_recommender.product.seed_service import SeedService
from music_recommender.storage.protocols import ApplicationSessionRecord


def get_api_service(request: Request) -> Any:
    return request.app.state.api_service


def get_product_auth_service(request: Request) -> ProductAuthService:
    service = getattr(request.app.state, "product_auth_service", None)
    if service is None:
        raise ApiConfigurationError("Spotify session authentication is not configured.")
    return cast(ProductAuthService, service)


def get_session_service(request: Request) -> SessionService:
    service = getattr(request.app.state, "session_service", None)
    if service is None:
        raise ApiConfigurationError("Spotify session authentication is not configured.")
    return cast(SessionService, service)


def get_csrf_protection(request: Request) -> CsrfProtection:
    protection = getattr(request.app.state, "csrf_protection", None)
    if protection is None:
        raise ApiConfigurationError("CSRF protection is not configured.")
    return cast(CsrfProtection, protection)


def get_seed_service(request: Request) -> SeedService:
    service = getattr(request.app.state, "seed_service", None)
    if service is None:
        raise ApiConfigurationError("Explicit seed discovery is not configured.")
    return cast(SeedService, service)


def get_discovery_job_service(request: Request) -> DiscoveryJobService:
    service = getattr(request.app.state, "discovery_job_service", None)
    if service is None:
        raise ApiConfigurationError("Automated discovery is not configured.")
    return cast(DiscoveryJobService, service)


def get_recommendation_service(request: Request) -> RecommendationService:
    service = getattr(request.app.state, "recommendation_service", None)
    if service is None:
        raise ApiConfigurationError("Product recommendations are not configured.")
    return cast(RecommendationService, service)


def get_playlist_export_service(request: Request) -> PlaylistExportService:
    service = getattr(request.app.state, "playlist_export_service", None)
    if service is None:
        raise ApiConfigurationError("Spotify playlist export is not configured.")
    return cast(PlaylistExportService, service)


def get_feedback_evaluation_service(request: Request) -> FeedbackEvaluationService:
    service = getattr(request.app.state, "feedback_evaluation_service", None)
    if service is None:
        raise ApiConfigurationError("Product feedback is not configured.")
    return cast(FeedbackEvaluationService, service)


def get_account_service(request: Request) -> AccountService:
    service = getattr(request.app.state, "account_service", None)
    if service is None:
        raise ApiConfigurationError("Account deletion is not configured.")
    return cast(AccountService, service)


def require_authenticated_session(
    request: Request,
    session_service: Annotated[SessionService, Depends(get_session_service)],
) -> ApplicationSessionRecord:
    session = session_service.authenticate(request.cookies.get(SESSION_COOKIE_NAME))
    mark_request_account(request, account_id=session.account_id)
    return session


def require_mutating_session(
    request: Request,
    session: Annotated[ApplicationSessionRecord, Depends(require_authenticated_session)],
    csrf_protection: Annotated[CsrfProtection, Depends(get_csrf_protection)],
) -> ApplicationSessionRecord:
    csrf_protection.validate(
        session=session,
        cookie_token=request.cookies.get(CSRF_COOKIE_NAME),
        header_token=request.headers.get("x-csrf-token"),
        origin=request.headers.get("origin"),
    )
    return session


def require_current_user(
    session: Annotated[ApplicationSessionRecord, Depends(require_authenticated_session)],
    auth_service: Annotated[ProductAuthService, Depends(get_product_auth_service)],
) -> ProductUser:
    return auth_service.current_user(session)


def require_approved_user(
    user: Annotated[ProductUser, Depends(require_current_user)],
) -> ProductUser:
    return _approved_user(user)


def require_approved_mutating_user(
    session: Annotated[ApplicationSessionRecord, Depends(require_mutating_session)],
    auth_service: Annotated[ProductAuthService, Depends(get_product_auth_service)],
) -> ProductUser:
    return _approved_user(auth_service.current_user(session))


def _approved_user(user: ProductUser) -> ProductUser:
    if user.access_status == "pending":
        raise ApiAccessPendingError("Beta access is pending approval.")
    if user.access_status == "revoked":
        raise ApiAccessRevokedError("Beta access has been revoked.")
    if user.reauthorization_required:
        raise ApiSpotifyReconnectRequiredError("Spotify reconnection is required.")
    return user
