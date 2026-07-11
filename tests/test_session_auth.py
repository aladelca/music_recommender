from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from starlette.responses import Response

from music_recommender.api.dependencies import (
    require_approved_user,
    require_authenticated_session,
    require_current_user,
    require_mutating_session,
)
from music_recommender.api.errors import register_error_handlers
from music_recommender.auth.models import ProductUser
from music_recommender.auth.sessions import (
    CSRF_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    CsrfProtection,
    CsrfValidationError,
    OriginValidationError,
    SessionAuthenticationError,
    SessionService,
    clear_auth_cookies,
    set_auth_cookies,
)
from music_recommender.storage.protocols import ApplicationSessionRecord


class InMemorySessionRepository:
    def __init__(self) -> None:
        self.records: dict[str, ApplicationSessionRecord] = {}
        self.revoked: list[tuple[str, str, datetime]] = []

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

    def touch(
        self,
        *,
        session_hash: str,
        account_id: str,
        last_seen_at: datetime,
        idle_expires_at: datetime,
    ) -> ApplicationSessionRecord | None:
        session = self.records.get(session_hash)
        if session is None or session.account_id != account_id or session.revoked_at is not None:
            return None
        updated = replace(
            session,
            last_seen_at=last_seen_at,
            idle_expires_at=min(idle_expires_at, session.absolute_expires_at),
        )
        self.records[session_hash] = updated
        return updated

    def revoke(
        self,
        *,
        session_hash: str,
        account_id: str,
        revoked_at: datetime,
    ) -> bool:
        session = self.records.get(session_hash)
        if session is None or session.account_id != account_id or session.revoked_at is not None:
            return False
        self.records[session_hash] = replace(session, revoked_at=revoked_at)
        self.revoked.append((session_hash, account_id, revoked_at))
        return True


def test_session_issue_hashes_tokens_and_sets_bounded_lifetimes() -> None:
    now = datetime(2030, 1, 1, 12, tzinfo=UTC)
    repository = InMemorySessionRepository()
    tokens = iter(("s" * 43, "c" * 43))
    service = SessionService(
        repository=repository, now=lambda: now, token_factory=lambda: next(tokens)
    )

    credentials = service.issue(account_id="account-1")

    record = credentials.record
    assert credentials.session_token == "s" * 43
    assert credentials.csrf_token == "c" * 43
    assert record.session_hash != credentials.session_token
    assert record.csrf_hash != credentials.csrf_token
    assert len(record.session_hash) == 64
    assert len(record.csrf_hash) == 64
    assert record.idle_expires_at == now + timedelta(days=7)
    assert record.absolute_expires_at == now + timedelta(days=30)
    assert record.last_seen_at == now
    assert credentials.session_token not in repr(credentials)
    assert credentials.csrf_token not in repr(credentials)


def test_session_authentication_extends_idle_expiry_but_not_absolute_expiry() -> None:
    issued_at = datetime(2030, 1, 1, tzinfo=UTC)
    current_time = issued_at
    repository = InMemorySessionRepository()
    tokens = iter(("s" * 43, "c" * 43))
    service = SessionService(
        repository=repository,
        now=lambda: current_time,
        token_factory=lambda: next(tokens),
    )
    credentials = service.issue(account_id="account-1")
    repository.records[credentials.record.session_hash] = replace(
        credentials.record,
        idle_expires_at=credentials.record.absolute_expires_at,
    )
    current_time = issued_at + timedelta(days=29)

    authenticated = service.authenticate(credentials.session_token)

    assert authenticated.last_seen_at == current_time
    assert authenticated.idle_expires_at == issued_at + timedelta(days=30)
    assert authenticated.absolute_expires_at == issued_at + timedelta(days=30)


def test_session_rotation_revokes_previous_browser_session() -> None:
    now = datetime(2030, 1, 1, tzinfo=UTC)
    repository = InMemorySessionRepository()
    tokens = iter(("a" * 43, "b" * 43, "c" * 43, "d" * 43))
    service = SessionService(
        repository=repository, now=lambda: now, token_factory=lambda: next(tokens)
    )
    previous = service.issue(account_id="old-account")

    rotated = service.issue(
        account_id="account-1",
        previous_session_token=previous.session_token,
    )

    assert repository.revoked == [(previous.record.session_hash, "old-account", now)]
    assert rotated.record.account_id == "account-1"
    with pytest.raises(SessionAuthenticationError):
        service.authenticate(previous.session_token)


def test_session_authentication_rejects_missing_unknown_and_expired_tokens() -> None:
    now = datetime(2030, 1, 1, tzinfo=UTC)
    repository = InMemorySessionRepository()
    service = SessionService(repository=repository, now=lambda: now)

    for token in (None, "", "unknown-token"):
        with pytest.raises(SessionAuthenticationError, match="Authentication required"):
            service.authenticate(token)


def test_csrf_protection_requires_exact_origin_and_double_submit_token() -> None:
    now = datetime(2030, 1, 1, tzinfo=UTC)
    repository = InMemorySessionRepository()
    tokens = iter(("s" * 43, "c" * 43))
    service = SessionService(
        repository=repository, now=lambda: now, token_factory=lambda: next(tokens)
    )
    credentials = service.issue(account_id="account-1")
    protection = CsrfProtection(allowed_origins=("https://outside-the-loop-beta.vercel.app",))

    protection.validate(
        session=credentials.record,
        cookie_token=credentials.csrf_token,
        header_token=credentials.csrf_token,
        origin="https://outside-the-loop-beta.vercel.app",
    )

    with pytest.raises(OriginValidationError, match="Origin"):
        protection.validate(
            session=credentials.record,
            cookie_token=credentials.csrf_token,
            header_token=credentials.csrf_token,
            origin="https://attacker.example",
        )
    with pytest.raises(CsrfValidationError, match="CSRF"):
        protection.validate(
            session=credentials.record,
            cookie_token=credentials.csrf_token,
            header_token="wrong-token",
            origin="https://outside-the-loop-beta.vercel.app",
        )


def test_auth_cookie_helpers_use_host_prefix_and_secure_attributes() -> None:
    now = datetime(2030, 1, 1, tzinfo=UTC)
    repository = InMemorySessionRepository()
    tokens = iter(("s" * 43, "c" * 43))
    service = SessionService(
        repository=repository, now=lambda: now, token_factory=lambda: next(tokens)
    )
    credentials = service.issue(account_id="account-1")
    response = Response()

    set_auth_cookies(response, credentials)

    cookies = response.headers.getlist("set-cookie")
    session_cookie = next(cookie for cookie in cookies if cookie.startswith(SESSION_COOKIE_NAME))
    csrf_cookie = next(cookie for cookie in cookies if cookie.startswith(CSRF_COOKIE_NAME))
    assert "HttpOnly" in session_cookie
    assert "HttpOnly" not in csrf_cookie
    for cookie in cookies:
        assert "Path=/" in cookie
        assert "SameSite=lax" in cookie
        assert "Secure" in cookie
        assert "Max-Age=2592000" in cookie

    clear_response = Response()
    clear_auth_cookies(clear_response)
    cleared = clear_response.headers.getlist("set-cookie")
    assert len(cleared) == 2
    assert all("Max-Age=0" in cookie for cookie in cleared)
    assert all("Secure" in cookie for cookie in cleared)


def test_fastapi_session_dependencies_enforce_authentication_origin_and_csrf() -> None:
    now = datetime(2030, 1, 1, tzinfo=UTC)
    repository = InMemorySessionRepository()
    tokens = iter(("s" * 43, "c" * 43))
    session_service = SessionService(
        repository=repository,
        now=lambda: now,
        token_factory=lambda: next(tokens),
    )
    credentials = session_service.issue(account_id="account-1")
    app = FastAPI()
    app.state.session_service = session_service
    app.state.csrf_protection = CsrfProtection(
        allowed_origins=("https://outside-the-loop-beta.vercel.app",)
    )
    register_error_handlers(app)

    @app.get("/protected")
    def protected_get(
        session: Annotated[
            ApplicationSessionRecord,
            Depends(require_authenticated_session),
        ],
    ) -> dict[str, str]:
        return {"account_id": session.account_id}

    @app.post("/protected")
    def protected_post(
        session: Annotated[
            ApplicationSessionRecord,
            Depends(require_mutating_session),
        ],
    ) -> dict[str, str]:
        return {"account_id": session.account_id}

    client = TestClient(app)
    assert client.get("/protected").status_code == 401

    cookie = (
        f"{SESSION_COOKIE_NAME}={credentials.session_token}; "
        f"{CSRF_COOKIE_NAME}={credentials.csrf_token}"
    )
    assert client.get("/protected", headers={"Cookie": cookie}).json() == {
        "account_id": "account-1"
    }
    rejected = client.post("/protected", headers={"Cookie": cookie})
    assert rejected.status_code == 403
    assert rejected.json()["code"] == "origin_not_allowed"

    accepted = client.post(
        "/protected",
        headers={
            "Cookie": cookie,
            "Origin": "https://outside-the-loop-beta.vercel.app",
            "X-CSRF-Token": credentials.csrf_token,
        },
    )
    assert accepted.status_code == 200
    assert accepted.json() == {"account_id": "account-1"}


@pytest.mark.parametrize(
    ("access_status", "reauthorization_required", "status_code", "code"),
    [
        ("pending", False, 403, "access_pending"),
        ("revoked", False, 403, "access_revoked"),
        ("approved", True, 409, "spotify_reconnect_required"),
    ],
)
def test_approved_user_dependency_returns_stable_access_errors(
    access_status: str,
    reauthorization_required: bool,
    status_code: int,
    code: str,
) -> None:
    app = FastAPI()
    register_error_handlers(app)
    user = ProductUser(
        account_id="account-1",
        display_name="Tester",
        access_status=access_status,  # type: ignore[arg-type]
        seed_ready=False,
        reauthorization_required=reauthorization_required,
    )
    app.dependency_overrides[require_current_user] = lambda: user

    @app.get("/approved")
    def approved(
        current: Annotated[ProductUser, Depends(require_approved_user)],
    ) -> dict[str, str]:
        return {"account_id": current.account_id}

    response = TestClient(app).get("/approved")

    assert response.status_code == status_code
    assert response.json()["code"] == code
