from __future__ import annotations

import hashlib
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from urllib.parse import unquote, urlsplit

from music_recommender.auth.models import (
    ConsumedOAuthState,
    OAuthAuthorizationRequest,
    OAuthLoginResult,
    ProductUser,
)
from music_recommender.auth.sessions import SessionAuthenticationError, SessionService
from music_recommender.sources.spotify_user import (
    SpotifyAccessToken,
    SpotifyClientError,
    SpotifyScopeError,
    build_authorization_url,
    generate_pkce_verifier,
    pkce_code_challenge,
)
from music_recommender.storage.protocols import (
    ApplicationSessionRecord,
    OAuthStateRecord,
    OAuthStateRepository,
    UserAccountRecord,
)


class OAuthStateError(ValueError):
    pass


class OAuthReturnPathError(ValueError):
    pass


class OAuthCallbackError(RuntimeError):
    pass


class OAuthVerifierVault(Protocol):
    def encrypt_oauth_verifier(self, *, state_hash: str, code_verifier: str) -> bytes: ...

    def decrypt_oauth_verifier(self, *, state_hash: str, ciphertext: bytes) -> str: ...


class RefreshTokenVault(Protocol):
    def encrypt_refresh_token(self, *, account_id: str, refresh_token: str) -> bytes: ...


class SeedReadRepository(Protocol):
    def list_active(self, *, account_id: str) -> tuple[Any, ...]: ...


class AuthUserRepository(Protocol):
    def get(self, *, account_id: str) -> UserAccountRecord | None: ...

    def upsert_pending(
        self,
        *,
        account_id: str,
        display_name: str | None,
        refresh_token_ciphertext: bytes,
        token_scopes: tuple[str, ...],
        token_issued_at: datetime,
        login_at: datetime,
    ) -> UserAccountRecord: ...


class SpotifyOAuthClient(Protocol):
    def exchange_authorization_code(
        self,
        *,
        code: str,
        redirect_uri: str,
        code_verifier: str | None = None,
        required_scopes: tuple[str, ...] = (),
    ) -> SpotifyAccessToken: ...

    def get_current_user_profile(self) -> dict[str, Any]: ...

    def close(self) -> None: ...


class OAuthService:
    def __init__(
        self,
        *,
        client_id: str,
        redirect_uri: str,
        scopes: tuple[str, ...],
        state_repository: OAuthStateRepository,
        verifier_vault: OAuthVerifierVault,
        allowed_return_paths: tuple[str, ...],
        state_ttl: timedelta = timedelta(minutes=10),
        now: Callable[[], datetime] | None = None,
        state_factory: Callable[[], str] | None = None,
        verifier_factory: Callable[[], str] | None = None,
    ) -> None:
        if state_ttl <= timedelta(0) or state_ttl > timedelta(minutes=30):
            raise ValueError(
                "OAuth state lifetime must be greater than zero and at most 30 minutes."
            )
        self.client_id = _required_text(client_id, "client_id")
        self.redirect_uri = _required_text(redirect_uri, "redirect_uri")
        self.scopes = scopes
        self.state_repository = state_repository
        self.verifier_vault = verifier_vault
        self.allowed_return_paths = _validated_allowed_roots(allowed_return_paths)
        self.state_ttl = state_ttl
        self.now = now or (lambda: datetime.now(UTC))
        self.state_factory = state_factory or (lambda: secrets.token_urlsafe(32))
        self.verifier_factory = verifier_factory or generate_pkce_verifier

    def start(self, *, return_to: str) -> OAuthAuthorizationRequest:
        return_path = _validated_return_path(return_to, self.allowed_return_paths)
        state = _validated_generated_secret(self.state_factory(), "OAuth state")
        state_hash = _sha256(state)
        verifier = self.verifier_factory()
        challenge = pkce_code_challenge(verifier)
        created_at = _aware_utc(self.now())
        expires_at = created_at + self.state_ttl
        verifier_ciphertext = self.verifier_vault.encrypt_oauth_verifier(
            state_hash=state_hash,
            code_verifier=verifier,
        )
        self.state_repository.put(
            OAuthStateRecord(
                state_hash=state_hash,
                verifier_ciphertext=verifier_ciphertext,
                return_path=return_path,
                expires_at=expires_at,
                created_at=created_at,
            )
        )
        return OAuthAuthorizationRequest(
            authorization_url=build_authorization_url(
                client_id=self.client_id,
                redirect_uri=self.redirect_uri,
                scopes=self.scopes,
                state=state,
                code_challenge=challenge,
            ),
            state=state,
            return_path=return_path,
            expires_at=expires_at,
        )

    def consume_state(self, state: str) -> ConsumedOAuthState:
        normalized_state = _validated_callback_state(state)
        state_hash = _sha256(normalized_state)
        record = self.state_repository.consume(
            state_hash=state_hash,
            now=_aware_utc(self.now()),
        )
        if record is None:
            raise OAuthStateError("OAuth state is invalid or expired.")
        verifier = self.verifier_vault.decrypt_oauth_verifier(
            state_hash=record.state_hash,
            ciphertext=record.verifier_ciphertext,
        )
        pkce_code_challenge(verifier)
        return ConsumedOAuthState(
            code_verifier=verifier,
            return_path=record.return_path,
        )


class ProductAuthService:
    def __init__(
        self,
        *,
        oauth: OAuthService,
        sessions: SessionService,
        users: AuthUserRepository,
        seeds: SeedReadRepository,
        token_vault: RefreshTokenVault,
        spotify_client_factory: Callable[[], SpotifyOAuthClient],
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.oauth = oauth
        self.sessions = sessions
        self.users = users
        self.seeds = seeds
        self.token_vault = token_vault
        self.spotify_client_factory = spotify_client_factory
        self.now = now or (lambda: datetime.now(UTC))

    def start(self, *, return_to: str) -> OAuthAuthorizationRequest:
        return self.oauth.start(return_to=return_to)

    def complete_callback(
        self,
        *,
        code: str,
        state: str,
        previous_session_token: str | None = None,
    ) -> OAuthLoginResult:
        normalized_code = code.strip()
        if not normalized_code or len(normalized_code) > 4_096:
            raise OAuthCallbackError("Spotify sign-in could not be completed.")
        consumed = self.oauth.consume_state(state)
        client = self.spotify_client_factory()
        try:
            token = client.exchange_authorization_code(
                code=normalized_code,
                redirect_uri=self.oauth.redirect_uri,
                code_verifier=consumed.code_verifier,
                required_scopes=self.oauth.scopes,
            )
            profile = client.get_current_user_profile()
        except (SpotifyClientError, SpotifyScopeError, KeyError, TypeError, ValueError):
            raise OAuthCallbackError("Spotify sign-in could not be completed.") from None
        finally:
            client.close()

        account_id = _profile_account_id(profile)
        if token.refresh_token is None:
            raise OAuthCallbackError("Spotify sign-in could not be completed.")
        issued_at = _aware_utc(self.now())
        ciphertext = self.token_vault.encrypt_refresh_token(
            account_id=account_id,
            refresh_token=token.refresh_token,
        )
        user = self.users.upsert_pending(
            account_id=account_id,
            display_name=_profile_display_name(profile),
            refresh_token_ciphertext=ciphertext,
            token_scopes=tuple(token.scope.split()),
            token_issued_at=issued_at,
            login_at=issued_at,
        )
        credentials = self.sessions.issue(
            account_id=account_id,
            previous_session_token=previous_session_token,
        )
        return OAuthLoginResult(
            user=self._safe_user(user),
            credentials=credentials,
            return_path=consumed.return_path,
        )

    def cancel_callback(self, *, state: str) -> None:
        self.oauth.consume_state(state)

    def current_user(self, session: ApplicationSessionRecord) -> ProductUser:
        user = self.users.get(account_id=session.account_id)
        if user is None:
            raise SessionAuthenticationError("Authentication required.")
        return self._safe_user(user)

    def _safe_user(self, user: UserAccountRecord) -> ProductUser:
        return ProductUser(
            account_id=user.account_id,
            display_name=user.display_name,
            access_status=user.access_status,
            seed_ready=bool(self.seeds.list_active(account_id=user.account_id)),
            reauthorization_required=user.reauthorization_required,
        )


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _required_text(value: str, name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} must not be empty.")
    return normalized


def _validated_generated_secret(value: str, name: str) -> str:
    if len(value) < 32 or len(value) > 512 or value.strip() != value:
        raise RuntimeError(f"{name} generation failed.")
    return value


def _validated_callback_state(state: str) -> str:
    if not state or len(state) > 512 or state.strip() != state:
        raise OAuthStateError("OAuth state is invalid or expired.")
    return state


def _validated_allowed_roots(paths: tuple[str, ...]) -> tuple[str, ...]:
    roots: list[str] = []
    for path in paths:
        split = urlsplit(path)
        if (
            not path.startswith("/")
            or path.startswith("//")
            or split.scheme
            or split.netloc
            or split.query
            or split.fragment
            or "\\" in path
        ):
            raise ValueError("Allowed OAuth return paths must be internal path roots.")
        roots.append(path.rstrip("/") or "/")
    if not roots:
        raise ValueError("At least one OAuth return path must be allowed.")
    return tuple(dict.fromkeys(roots))


def _validated_return_path(return_to: str, allowed_roots: tuple[str, ...]) -> str:
    if not return_to or len(return_to) > 2_048 or any(ord(char) < 32 for char in return_to):
        raise OAuthReturnPathError("OAuth return path is not allowed.")
    split = urlsplit(return_to)
    decoded_path = unquote(split.path)
    if (
        split.scheme
        or split.netloc
        or split.fragment
        or not split.path.startswith("/")
        or split.path.startswith("//")
        or decoded_path.startswith("//")
        or "\\" in decoded_path
        or any(segment in {".", ".."} for segment in decoded_path.split("/"))
    ):
        raise OAuthReturnPathError("OAuth return path is not allowed.")
    if not any(
        decoded_path == root or (root != "/" and decoded_path.startswith(f"{root}/"))
        for root in allowed_roots
    ):
        raise OAuthReturnPathError("OAuth return path is not allowed.")
    return return_to


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Authentication timestamps must be timezone-aware.")
    return value.astimezone(UTC)


def _profile_account_id(profile: dict[str, Any]) -> str:
    value = profile.get("account_id")
    if not isinstance(value, str):
        raise OAuthCallbackError("Spotify sign-in could not be completed.")
    account_id = value.strip()
    if not account_id or len(account_id) > 255:
        raise OAuthCallbackError("Spotify sign-in could not be completed.")
    return account_id


def _profile_display_name(profile: dict[str, Any]) -> str | None:
    value = profile.get("display_name")
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized[:200] or None
