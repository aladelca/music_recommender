from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from music_recommender.api.dependencies import (
    get_account_service,
    get_product_auth_service,
    get_session_service,
    require_authenticated_session,
    require_mutating_session,
)
from music_recommender.api.models import AccountDeletionRequest
from music_recommender.auth.models import OAuthLoginResult
from music_recommender.auth.oauth import (
    OAuthCallbackError,
    OAuthStateError,
    ProductAuthService,
)
from music_recommender.auth.sessions import (
    SESSION_COOKIE_NAME,
    SessionService,
    clear_auth_cookies,
    set_auth_cookies,
)
from music_recommender.product.account_service import AccountService
from music_recommender.storage.protocols import ApplicationSessionRecord

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.get("/spotify/start")
def spotify_start(
    service: Annotated[ProductAuthService, Depends(get_product_auth_service)],
    return_to: Annotated[str, Query(min_length=1, max_length=2_048)] = "/discover",
) -> RedirectResponse:
    started = service.start(return_to=return_to)
    return RedirectResponse(started.authorization_url, status_code=302)


@router.get("/spotify/callback")
def spotify_callback(
    request: Request,
    service: Annotated[ProductAuthService, Depends(get_product_auth_service)],
    state: Annotated[str, Query(min_length=1, max_length=512)],
    code: Annotated[str | None, Query(min_length=1, max_length=4_096)] = None,
    error: Annotated[str | None, Query(min_length=1, max_length=128)] = None,
) -> RedirectResponse:
    try:
        if error is not None:
            service.cancel_callback(state=state)
            error_code = "access_denied" if error == "access_denied" else "spotify_error"
            return RedirectResponse(f"/?oauth_error={error_code}", status_code=302)
        if code is None:
            raise OAuthCallbackError("Spotify sign-in could not be completed.")
        result = service.complete_callback(
            code=code,
            state=state,
            previous_session_token=request.cookies.get(SESSION_COOKIE_NAME),
        )
    except OAuthStateError:
        return RedirectResponse("/?oauth_error=expired_state", status_code=302)
    except OAuthCallbackError:
        return RedirectResponse("/?oauth_error=spotify_error", status_code=302)
    response = RedirectResponse(_login_destination(result), status_code=302)
    set_auth_cookies(response, result.credentials)
    return response


@router.get("/me")
def auth_me(
    session: Annotated[ApplicationSessionRecord, Depends(require_authenticated_session)],
    service: Annotated[ProductAuthService, Depends(get_product_auth_service)],
) -> JSONResponse:
    return JSONResponse(service.current_user(session).to_dict())


@router.delete("/me", status_code=204)
def delete_account(
    request: AccountDeletionRequest,
    session: Annotated[ApplicationSessionRecord, Depends(require_mutating_session)],
    service: Annotated[AccountService, Depends(get_account_service)],
) -> Response:
    service.delete(
        account_id=session.account_id,
        confirmation=request.confirmation,
    )
    response = Response(status_code=204)
    clear_auth_cookies(response)
    return response


@router.post("/logout", status_code=204)
def logout(
    request: Request,
    session: Annotated[ApplicationSessionRecord, Depends(require_mutating_session)],
    session_service: Annotated[SessionService, Depends(get_session_service)],
) -> Response:
    del session
    session_service.revoke(request.cookies.get(SESSION_COOKIE_NAME))
    response = Response(status_code=204)
    clear_auth_cookies(response)
    return response


def _login_destination(result: OAuthLoginResult) -> str:
    if result.user.access_status == "pending":
        return "/access-pending"
    if result.user.access_status == "revoked":
        return "/access-revoked"
    if not result.user.seed_ready:
        return "/onboarding/seeds"
    return result.return_path
