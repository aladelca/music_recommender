from __future__ import annotations

import hashlib
import hmac
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from starlette.responses import Response

from music_recommender.auth.models import SessionCredentials
from music_recommender.storage.protocols import (
    ApplicationSessionRecord,
    ApplicationSessionRepository,
)

SESSION_COOKIE_NAME = "__Host-mr_session"
CSRF_COOKIE_NAME = "__Host-mr_csrf"


class SessionAuthenticationError(RuntimeError):
    pass


class CsrfValidationError(RuntimeError):
    pass


class OriginValidationError(RuntimeError):
    pass


class SessionService:
    def __init__(
        self,
        *,
        repository: ApplicationSessionRepository,
        idle_lifetime: timedelta = timedelta(days=7),
        absolute_lifetime: timedelta = timedelta(days=30),
        now: Callable[[], datetime] | None = None,
        token_factory: Callable[[], str] | None = None,
    ) -> None:
        if idle_lifetime <= timedelta(0):
            raise ValueError("Session idle lifetime must be positive.")
        if absolute_lifetime < idle_lifetime or absolute_lifetime > timedelta(days=90):
            raise ValueError(
                "Session absolute lifetime must cover the idle lifetime and be at most 90 days."
            )
        self.repository = repository
        self.idle_lifetime = idle_lifetime
        self.absolute_lifetime = absolute_lifetime
        self.now = now or (lambda: datetime.now(UTC))
        self.token_factory = token_factory or (lambda: secrets.token_urlsafe(32))

    def issue(
        self,
        *,
        account_id: str,
        previous_session_token: str | None = None,
    ) -> SessionCredentials:
        normalized_account_id = _required_text(account_id, "account_id")
        issued_at = _aware_utc(self.now())
        if previous_session_token:
            previous = self.repository.get_active(
                session_hash=_hash_untrusted_token(previous_session_token),
                now=issued_at,
            )
            if previous is not None:
                self.repository.revoke(
                    session_hash=previous.session_hash,
                    account_id=previous.account_id,
                    revoked_at=issued_at,
                )

        session_token = _validated_generated_token(self.token_factory())
        csrf_token = _validated_generated_token(self.token_factory())
        absolute_expires_at = issued_at + self.absolute_lifetime
        record = ApplicationSessionRecord(
            session_hash=_sha256(session_token),
            account_id=normalized_account_id,
            csrf_hash=_sha256(csrf_token),
            idle_expires_at=min(issued_at + self.idle_lifetime, absolute_expires_at),
            absolute_expires_at=absolute_expires_at,
            last_seen_at=issued_at,
            created_at=issued_at,
        )
        self.repository.put(record)
        return SessionCredentials(
            session_token=session_token,
            csrf_token=csrf_token,
            record=record,
            max_age_seconds=int(self.absolute_lifetime.total_seconds()),
        )

    def authenticate(self, session_token: str | None) -> ApplicationSessionRecord:
        normalized_token = _normalized_untrusted_token(session_token)
        if normalized_token is None:
            raise SessionAuthenticationError("Authentication required.")
        now = _aware_utc(self.now())
        session = self.repository.get_active(
            session_hash=_sha256(normalized_token),
            now=now,
        )
        if session is None:
            raise SessionAuthenticationError("Authentication required.")
        touched = self.repository.touch(
            session_hash=session.session_hash,
            account_id=session.account_id,
            last_seen_at=now,
            idle_expires_at=min(now + self.idle_lifetime, session.absolute_expires_at),
        )
        if touched is None:
            raise SessionAuthenticationError("Authentication required.")
        return touched

    def revoke(self, session_token: str | None) -> bool:
        normalized_token = _normalized_untrusted_token(session_token)
        if normalized_token is None:
            return False
        now = _aware_utc(self.now())
        session = self.repository.get_active(session_hash=_sha256(normalized_token), now=now)
        if session is None:
            return False
        return self.repository.revoke(
            session_hash=session.session_hash,
            account_id=session.account_id,
            revoked_at=now,
        )


class CsrfProtection:
    def __init__(self, *, allowed_origins: tuple[str, ...]) -> None:
        origins = tuple(_canonical_origin(origin) for origin in allowed_origins)
        if not origins:
            raise ValueError("At least one allowed Origin is required.")
        self.allowed_origins = frozenset(origins)

    def validate(
        self,
        *,
        session: ApplicationSessionRecord,
        cookie_token: str | None,
        header_token: str | None,
        origin: str | None,
    ) -> None:
        try:
            normalized_origin = _canonical_origin(origin or "")
        except ValueError:
            raise OriginValidationError("Origin is not allowed.") from None
        if normalized_origin not in self.allowed_origins:
            raise OriginValidationError("Origin is not allowed.")
        cookie = _normalized_untrusted_token(cookie_token)
        header = _normalized_untrusted_token(header_token)
        if cookie is None or header is None or not hmac.compare_digest(cookie, header):
            raise CsrfValidationError("CSRF validation failed.")
        if not hmac.compare_digest(_sha256(cookie), session.csrf_hash):
            raise CsrfValidationError("CSRF validation failed.")


def set_auth_cookies(response: Response, credentials: SessionCredentials) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=credentials.session_token,
        max_age=credentials.max_age_seconds,
        path="/",
        secure=True,
        httponly=True,
        samesite="lax",
    )
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=credentials.csrf_token,
        max_age=credentials.max_age_seconds,
        path="/",
        secure=True,
        httponly=False,
        samesite="lax",
    )


def clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/",
        secure=True,
        httponly=True,
        samesite="lax",
    )
    response.delete_cookie(
        key=CSRF_COOKIE_NAME,
        path="/",
        secure=True,
        httponly=False,
        samesite="lax",
    )


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _hash_untrusted_token(value: str) -> str:
    normalized = _normalized_untrusted_token(value)
    if normalized is None:
        return _sha256("")
    return _sha256(normalized)


def _normalized_untrusted_token(value: str | None) -> str | None:
    if value is None or not value or len(value) > 512 or value.strip() != value:
        return None
    return value


def _validated_generated_token(value: str) -> str:
    if len(value) < 32 or len(value) > 512 or value.strip() != value:
        raise RuntimeError("Secure session token generation failed.")
    return value


def _required_text(value: str, name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} must not be empty.")
    return normalized


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Authentication timestamps must be timezone-aware.")
    return value.astimezone(UTC)


def _canonical_origin(origin: str) -> str:
    split = urlsplit(origin)
    if (
        split.scheme not in {"http", "https"}
        or not split.hostname
        or split.username is not None
        or split.password is not None
        or split.path not in {"", "/"}
        or split.query
        or split.fragment
    ):
        raise ValueError("Origin must be an HTTP origin without a path.")
    if split.scheme != "https" and split.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("Non-local origins must use HTTPS.")
    host = split.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    default_port = 443 if split.scheme == "https" else 80
    port = f":{split.port}" if split.port and split.port != default_port else ""
    return f"{split.scheme}://{host}{port}"
