from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from music_recommender.auth.oauth import (
    OAuthCallbackError,
    OAuthReturnPathError,
    OAuthStateError,
)
from music_recommender.auth.sessions import (
    CsrfValidationError,
    OriginValidationError,
    SessionAuthenticationError,
)
from music_recommender.observability import mark_request_error
from music_recommender.product.account_service import (
    AccountDeletionConfirmationError,
    AccountDeletionNotFoundError,
)
from music_recommender.product.discovery_queue import DiscoveryQueueUnavailableError
from music_recommender.product.discovery_service import (
    DiscoveryJobNotFoundError,
    DiscoverySeedsRequiredError,
)
from music_recommender.product.feedback_service import (
    ProductFeedbackConflictError,
    ProductFeedbackNotFoundError,
    ProductFeedbackValidationError,
)
from music_recommender.product.playlist_export_service import (
    PlaylistExportConflictError,
    PlaylistExportNotFoundError,
    PlaylistExportReviewRequiredError,
    PlaylistExportUnavailableError,
)
from music_recommender.product.recommendation_service import (
    RecommendationCursorError,
    RecommendationNotFoundError,
    RecommendationSeedOwnershipError,
    RecommendationSelectionError,
)
from music_recommender.product.spotify_account import SpotifyAccountUnavailableError
from music_recommender.security.token_vault import TokenVaultError
from music_recommender.sources.spotify_user import (
    SpotifyPermissionDenied,
    SpotifyRateLimited,
    SpotifyReauthorizationRequired,
    SpotifyResponseError,
    SpotifyServiceUnavailable,
)


class ApiConfigurationError(RuntimeError):
    pass


class ApiValidationError(ValueError):
    pass


class ApiNotFoundError(LookupError):
    pass


class ApiAccessPendingError(RuntimeError):
    pass


class ApiAccessRevokedError(RuntimeError):
    pass


class ApiSpotifyReconnectRequiredError(RuntimeError):
    pass


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AccountDeletionConfirmationError)
    def account_deletion_confirmation_error_handler(
        request: Request,
        exc: AccountDeletionConfirmationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={"detail": str(exc), "code": "account_deletion_confirmation_required"},
        )

    @app.exception_handler(AccountDeletionNotFoundError)
    def account_deletion_not_found_error_handler(
        request: Request,
        exc: AccountDeletionNotFoundError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"detail": str(exc), "code": "account_not_found"},
        )

    @app.exception_handler(ProductFeedbackNotFoundError)
    def product_feedback_not_found_error_handler(
        request: Request,
        exc: ProductFeedbackNotFoundError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"detail": str(exc), "code": "recommendation_item_not_found"},
        )

    @app.exception_handler(ProductFeedbackConflictError)
    def product_feedback_conflict_error_handler(
        request: Request,
        exc: ProductFeedbackConflictError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={"detail": str(exc), "code": "idempotency_conflict"},
        )

    @app.exception_handler(ProductFeedbackValidationError)
    def product_feedback_validation_error_handler(
        request: Request,
        exc: ProductFeedbackValidationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={"detail": str(exc), "code": "invalid_feedback"},
        )

    @app.exception_handler(PlaylistExportNotFoundError)
    def playlist_export_not_found_error_handler(
        request: Request,
        exc: PlaylistExportNotFoundError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"detail": str(exc), "code": "recommendation_not_found"},
        )

    @app.exception_handler(PlaylistExportReviewRequiredError)
    def playlist_export_review_error_handler(
        request: Request,
        exc: PlaylistExportReviewRequiredError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={"detail": str(exc), "code": "playlist_review_required"},
        )

    @app.exception_handler(PlaylistExportConflictError)
    def playlist_export_conflict_error_handler(
        request: Request,
        exc: PlaylistExportConflictError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={"detail": str(exc), "code": "idempotency_conflict"},
        )

    @app.exception_handler(PlaylistExportUnavailableError)
    def playlist_export_unavailable_error_handler(
        request: Request,
        exc: PlaylistExportUnavailableError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=502,
            content={"detail": str(exc), "code": "spotify_invalid_response"},
        )

    @app.exception_handler(RecommendationNotFoundError)
    def recommendation_not_found_error_handler(
        request: Request,
        exc: RecommendationNotFoundError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"detail": str(exc), "code": "recommendation_not_found"},
        )

    @app.exception_handler(RecommendationSeedOwnershipError)
    def recommendation_seed_not_found_error_handler(
        request: Request,
        exc: RecommendationSeedOwnershipError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"detail": str(exc), "code": "recommendation_seed_not_found"},
        )

    @app.exception_handler(RecommendationSelectionError)
    def recommendation_selection_error_handler(
        request: Request,
        exc: RecommendationSelectionError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={"detail": str(exc), "code": "invalid_recommendation_selection"},
        )

    @app.exception_handler(RecommendationCursorError)
    def recommendation_cursor_error_handler(
        request: Request,
        exc: RecommendationCursorError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={"detail": str(exc), "code": "invalid_recommendation_cursor"},
        )

    @app.exception_handler(SpotifyAccountUnavailableError)
    def spotify_account_unavailable_error_handler(
        request: Request,
        exc: SpotifyAccountUnavailableError,
    ) -> JSONResponse:
        mark_request_error(request, error_code="spotify_reconnect_required")
        return JSONResponse(
            status_code=409,
            content={"detail": str(exc), "code": "spotify_reconnect_required"},
        )

    @app.exception_handler(SpotifyReauthorizationRequired)
    def spotify_reauthorization_error_handler(
        request: Request,
        exc: SpotifyReauthorizationRequired,
    ) -> JSONResponse:
        mark_request_error(request, error_code="spotify_reconnect_required")
        return JSONResponse(
            status_code=409,
            content={"detail": str(exc), "code": "spotify_reconnect_required"},
        )

    @app.exception_handler(SpotifyPermissionDenied)
    def spotify_permission_error_handler(
        request: Request,
        exc: SpotifyPermissionDenied,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=403,
            content={"detail": str(exc), "code": "spotify_permission_denied"},
        )

    @app.exception_handler(SpotifyRateLimited)
    @app.exception_handler(SpotifyServiceUnavailable)
    def spotify_unavailable_error_handler(
        request: Request,
        exc: SpotifyRateLimited | SpotifyServiceUnavailable,
    ) -> JSONResponse:
        mark_request_error(request, error_code="spotify_temporarily_unavailable")
        return JSONResponse(
            status_code=503,
            content={"detail": str(exc), "code": "spotify_temporarily_unavailable"},
        )

    @app.exception_handler(SpotifyResponseError)
    def spotify_response_error_handler(
        request: Request,
        exc: SpotifyResponseError,
    ) -> JSONResponse:
        mark_request_error(request, error_code="spotify_invalid_response")
        return JSONResponse(
            status_code=502,
            content={"detail": str(exc), "code": "spotify_invalid_response"},
        )

    @app.exception_handler(TokenVaultError)
    def token_vault_error_handler(
        request: Request,
        exc: TokenVaultError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={"detail": str(exc), "code": "credential_service_unavailable"},
        )

    @app.exception_handler(DiscoveryQueueUnavailableError)
    def discovery_queue_unavailable_error_handler(
        request: Request,
        exc: DiscoveryQueueUnavailableError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={"detail": str(exc), "code": "discovery_queue_unavailable"},
        )

    @app.exception_handler(DiscoverySeedsRequiredError)
    def discovery_seeds_required_error_handler(
        request: Request,
        exc: DiscoverySeedsRequiredError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={"detail": str(exc), "code": "discovery_seeds_required"},
        )

    @app.exception_handler(DiscoveryJobNotFoundError)
    def discovery_job_not_found_error_handler(
        request: Request,
        exc: DiscoveryJobNotFoundError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"detail": str(exc), "code": "discovery_job_not_found"},
        )

    @app.exception_handler(ApiAccessPendingError)
    def access_pending_error_handler(
        request: Request,
        exc: ApiAccessPendingError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=403,
            content={"detail": str(exc), "code": "access_pending"},
        )

    @app.exception_handler(ApiAccessRevokedError)
    def access_revoked_error_handler(
        request: Request,
        exc: ApiAccessRevokedError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=403,
            content={"detail": str(exc), "code": "access_revoked"},
        )

    @app.exception_handler(ApiSpotifyReconnectRequiredError)
    def spotify_reconnect_required_error_handler(
        request: Request,
        exc: ApiSpotifyReconnectRequiredError,
    ) -> JSONResponse:
        mark_request_error(request, error_code="spotify_reconnect_required")
        return JSONResponse(
            status_code=409,
            content={"detail": str(exc), "code": "spotify_reconnect_required"},
        )

    @app.exception_handler(OAuthReturnPathError)
    def oauth_return_path_error_handler(
        request: Request,
        exc: OAuthReturnPathError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={"detail": str(exc), "code": "invalid_return_path"},
        )

    @app.exception_handler(OAuthStateError)
    def oauth_state_error_handler(
        request: Request,
        exc: OAuthStateError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={"detail": str(exc), "code": "invalid_oauth_state"},
        )

    @app.exception_handler(OAuthCallbackError)
    def oauth_callback_error_handler(
        request: Request,
        exc: OAuthCallbackError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=401,
            content={"detail": str(exc), "code": "spotify_oauth_failed"},
        )

    @app.exception_handler(SessionAuthenticationError)
    def session_authentication_error_handler(
        request: Request,
        exc: SessionAuthenticationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=401,
            content={"detail": str(exc), "code": "authentication_required"},
        )

    @app.exception_handler(OriginValidationError)
    def origin_validation_error_handler(
        request: Request,
        exc: OriginValidationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=403,
            content={"detail": str(exc), "code": "origin_not_allowed"},
        )

    @app.exception_handler(CsrfValidationError)
    def csrf_validation_error_handler(
        request: Request,
        exc: CsrfValidationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=403,
            content={"detail": str(exc), "code": "csrf_validation_failed"},
        )

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
