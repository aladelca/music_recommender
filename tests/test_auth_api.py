from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from music_recommender.api.app import create_app
from music_recommender.auth.models import (
    OAuthAuthorizationRequest,
    OAuthLoginResult,
    ProductUser,
)
from music_recommender.auth.oauth import OAuthCallbackError, OAuthStateError
from music_recommender.auth.sessions import (
    CSRF_COOKIE_NAME,
    CsrfProtection,
    SessionService,
)
from music_recommender.storage.protocols import ApplicationSessionRecord


class InMemorySessionRepository:
    def __init__(self) -> None:
        self.records: dict[str, ApplicationSessionRecord] = {}

    def put(self, session: ApplicationSessionRecord) -> None:
        self.records[session.session_hash] = session

    def get_active(
        self,
        *,
        session_hash: str,
        now: datetime,
    ) -> ApplicationSessionRecord | None:
        session = self.records.get(session_hash)
        if (
            session is None
            or session.revoked_at is not None
            or session.idle_expires_at <= now
            or session.absolute_expires_at <= now
        ):
            return None
        return session

    def touch(self, **kwargs: Any) -> ApplicationSessionRecord | None:
        session = self.records.get(str(kwargs["session_hash"]))
        if session is None:
            return None
        return session

    def revoke(
        self,
        *,
        session_hash: str,
        account_id: str,
        revoked_at: datetime,
    ) -> bool:
        session = self.records.get(session_hash)
        if session is None or session.account_id != account_id:
            return False
        self.records[session_hash] = ApplicationSessionRecord(
            session_hash=session.session_hash,
            account_id=session.account_id,
            csrf_hash=session.csrf_hash,
            idle_expires_at=session.idle_expires_at,
            absolute_expires_at=session.absolute_expires_at,
            last_seen_at=session.last_seen_at,
            created_at=session.created_at,
            revoked_at=revoked_at,
        )
        return True


class FakeProductAuthService:
    def __init__(
        self,
        *,
        sessions: SessionService,
        access_status: str = "pending",
        seed_ready: bool = False,
        callback_error: Exception | None = None,
    ) -> None:
        self.sessions = sessions
        self.access_status = access_status
        self.seed_ready = seed_ready
        self.callback_error = callback_error
        self.start_return_paths: list[str] = []
        self.callback_calls: list[dict[str, Any]] = []
        self.cancel_calls: list[str] = []

    def start(self, *, return_to: str) -> OAuthAuthorizationRequest:
        self.start_return_paths.append(return_to)
        return OAuthAuthorizationRequest(
            authorization_url="https://accounts.spotify.com/authorize?state=opaque-state",
            state="opaque-state",
            return_path=return_to,
            expires_at=datetime(2030, 1, 1, 0, 10, tzinfo=UTC),
        )

    def complete_callback(
        self,
        *,
        code: str,
        state: str,
        previous_session_token: str | None = None,
    ) -> OAuthLoginResult:
        self.callback_calls.append(
            {"code": code, "state": state, "previous_session_token": previous_session_token}
        )
        if self.callback_error is not None:
            raise self.callback_error
        credentials = self.sessions.issue(
            account_id="account-1",
            previous_session_token=previous_session_token,
        )
        return OAuthLoginResult(
            user=self._user(),
            credentials=credentials,
            return_path="/discover",
        )

    def current_user(self, session: ApplicationSessionRecord) -> ProductUser:
        assert session.account_id == "account-1"
        return self._user()

    def cancel_callback(self, *, state: str) -> None:
        self.cancel_calls.append(state)

    def _user(self) -> ProductUser:
        return ProductUser(
            account_id="account-1",
            display_name="Tester",
            access_status=self.access_status,  # type: ignore[arg-type]
            seed_ready=self.seed_ready,
            reauthorization_required=False,
        )


def test_spotify_start_is_public_in_hybrid_mode_and_redirects_to_authorization() -> None:
    client, auth = build_client()

    response = client.get(
        "/auth/spotify/start?return_to=/discover",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"].startswith("https://accounts.spotify.com/authorize")
    assert auth.start_return_paths == ["/discover"]


@pytest.mark.parametrize(
    ("access_status", "seed_ready", "expected_location"),
    [
        ("pending", False, "/access-pending"),
        ("revoked", False, "/access-revoked"),
        ("approved", False, "/onboarding/seeds"),
        ("approved", True, "/discover"),
    ],
)
def test_spotify_callback_sets_secure_cookies_and_uses_access_redirect(
    access_status: str,
    seed_ready: bool,
    expected_location: str,
) -> None:
    client, auth = build_client(access_status=access_status, seed_ready=seed_ready)

    response = client.get(
        "/auth/spotify/callback?code=authorization-code&state=opaque-state",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"] == expected_location
    assert "__Host-mr_session=" in response.headers.get_list("set-cookie")[0]
    assert any(CSRF_COOKIE_NAME in cookie for cookie in response.headers.get_list("set-cookie"))
    assert auth.callback_calls == [
        {
            "code": "authorization-code",
            "state": "opaque-state",
            "previous_session_token": None,
        }
    ]


def test_auth_me_and_logout_use_session_and_csrf_dependencies() -> None:
    client, _ = build_client(access_status="approved", seed_ready=True)
    callback = client.get(
        "/auth/spotify/callback?code=authorization-code&state=opaque-state",
        follow_redirects=False,
    )
    assert callback.status_code == 302

    current = client.get("/auth/me")
    assert current.status_code == 200
    assert current.json() == {
        "account_id": "account-1",
        "display_name": "Tester",
        "access_status": "approved",
        "seed_ready": True,
        "reauthorization_required": False,
    }

    rejected = client.post("/auth/logout")
    assert rejected.status_code == 403
    csrf_token = client.cookies.get(CSRF_COOKIE_NAME)
    logged_out = client.post(
        "/auth/logout",
        headers={
            "Origin": "https://outside-the-loop-beta.vercel.app",
            "X-CSRF-Token": str(csrf_token),
        },
    )
    assert logged_out.status_code == 204
    assert client.get("/auth/me").status_code == 401


def test_oauth_state_failure_returns_stable_redacted_error() -> None:
    client, _ = build_client(callback_error=OAuthStateError("OAuth state is invalid or expired."))

    response = client.get(
        "/auth/spotify/callback?code=secret-code&state=secret-state",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"] == "/?oauth_error=expired_state"
    assert "secret-code" not in response.text
    assert "secret-state" not in response.text


def test_spotify_callback_failure_returns_to_login_without_provider_details() -> None:
    client, _ = build_client(
        callback_error=OAuthCallbackError("Spotify sign-in could not be completed.")
    )

    response = client.get(
        "/auth/spotify/callback?code=secret-code&state=secret-state",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"] == "/?oauth_error=spotify_error"
    assert "secret-code" not in response.text


def test_spotify_consent_denial_consumes_state_and_returns_to_login() -> None:
    client, auth = build_client()

    response = client.get(
        "/auth/spotify/callback?error=access_denied&state=opaque-state",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"] == "/?oauth_error=access_denied"
    assert auth.cancel_calls == ["opaque-state"]
    assert not response.headers.get_list("set-cookie")


def test_auth_routes_are_disabled_in_api_key_only_mode() -> None:
    client, _ = build_client(auth_mode="api_key")

    response = client.get("/auth/spotify/start", follow_redirects=False)

    assert response.status_code == 404
    assert response.json()["code"] == "route_disabled"


def build_client(
    *,
    auth_mode: str = "hybrid",
    access_status: str = "pending",
    seed_ready: bool = False,
    callback_error: Exception | None = None,
) -> tuple[TestClient, FakeProductAuthService]:
    now = datetime(2030, 1, 1, tzinfo=UTC)
    tokens = iter(("s" * 43, "c" * 43, "x" * 43, "y" * 43))
    sessions = SessionService(
        repository=InMemorySessionRepository(),
        now=lambda: now,
        token_factory=lambda: next(tokens),
    )
    auth = FakeProductAuthService(
        sessions=sessions,
        access_status=access_status,
        seed_ready=seed_ready,
        callback_error=callback_error,
    )
    app = create_app(
        load_env=False,
        auth_mode=auth_mode,
        product_auth_service=auth,
        session_service=sessions,
        csrf_protection=CsrfProtection(
            allowed_origins=("https://outside-the-loop-beta.vercel.app",)
        ),
    )
    return TestClient(app, base_url="https://outside-the-loop-beta.vercel.app"), auth
