from __future__ import annotations

import hashlib
import urllib.parse
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from music_recommender.auth.oauth import (
    OAuthCallbackError,
    OAuthReturnPathError,
    OAuthService,
    OAuthStateError,
    ProductAuthService,
)
from music_recommender.auth.sessions import SessionService
from music_recommender.sources.spotify_user import SpotifyAccessToken
from music_recommender.storage.protocols import (
    ApplicationSessionRecord,
    OAuthStateRecord,
    UserAccountRecord,
)


class InMemoryOAuthStateRepository:
    def __init__(self) -> None:
        self.records: dict[str, OAuthStateRecord] = {}

    def put(self, state: OAuthStateRecord) -> None:
        self.records[state.state_hash] = state

    def consume(self, *, state_hash: str, now: datetime) -> OAuthStateRecord | None:
        state = self.records.pop(state_hash, None)
        if state is None or state.expires_at <= now:
            return None
        return state


class FakeOAuthVerifierVault:
    def __init__(self) -> None:
        self.verifiers: dict[str, str] = {}
        self.encrypt_calls: list[tuple[str, str]] = []
        self.decrypt_calls: list[tuple[str, bytes]] = []

    def encrypt_oauth_verifier(self, *, state_hash: str, code_verifier: str) -> bytes:
        self.encrypt_calls.append((state_hash, code_verifier))
        self.verifiers[state_hash] = code_verifier
        return b"encrypted-verifier"

    def decrypt_oauth_verifier(self, *, state_hash: str, ciphertext: bytes) -> str:
        self.decrypt_calls.append((state_hash, ciphertext))
        return self.verifiers[state_hash]

    def encrypt_refresh_token(self, *, account_id: str, refresh_token: str) -> bytes:
        self.refresh_token_call = (account_id, refresh_token)
        return b"encrypted-refresh-token"


class InMemoryUserRepository:
    def __init__(self, *, existing_status: str = "pending") -> None:
        self.records: dict[str, UserAccountRecord] = {}
        self.existing_status = existing_status
        self.upsert_calls: list[dict[str, Any]] = []

    def get(self, *, account_id: str) -> UserAccountRecord | None:
        return self.records.get(account_id)

    def upsert_pending(
        self,
        *,
        account_id: str,
        display_name: str | None,
        refresh_token_ciphertext: bytes,
        token_scopes: tuple[str, ...],
        token_issued_at: datetime,
        login_at: datetime,
    ) -> UserAccountRecord:
        self.upsert_calls.append(
            {
                "account_id": account_id,
                "display_name": display_name,
                "refresh_token_ciphertext": refresh_token_ciphertext,
                "token_scopes": token_scopes,
                "token_issued_at": token_issued_at,
                "login_at": login_at,
            }
        )
        existing = self.records.get(account_id)
        record = user_record(
            account_id=account_id,
            access_status=(existing.access_status if existing else self.existing_status),
            display_name=display_name,
            now=login_at,
            ciphertext=refresh_token_ciphertext,
            scopes=token_scopes,
        )
        self.records[account_id] = record
        return record


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
        record = self.records.get(session_hash)
        if record and record.revoked_at is None and record.idle_expires_at > now:
            return record
        return None

    def touch(
        self,
        *,
        session_hash: str,
        account_id: str,
        last_seen_at: datetime,
        idle_expires_at: datetime,
    ) -> ApplicationSessionRecord | None:
        record = self.records.get(session_hash)
        if record is None or record.account_id != account_id:
            return None
        touched = replace(record, last_seen_at=last_seen_at, idle_expires_at=idle_expires_at)
        self.records[session_hash] = touched
        return touched

    def revoke(
        self,
        *,
        session_hash: str,
        account_id: str,
        revoked_at: datetime,
    ) -> bool:
        record = self.records.get(session_hash)
        if record is None or record.account_id != account_id:
            return False
        self.records[session_hash] = replace(record, revoked_at=revoked_at)
        return True


class FakeSeedRepository:
    def __init__(self, count: int = 0) -> None:
        self.count = count

    def list_active(self, *, account_id: str) -> tuple[Any, ...]:
        return tuple(object() for _ in range(self.count))


class FakeSpotifyOAuthClient:
    def __init__(self, *, profile: dict[str, Any] | None = None) -> None:
        self.profile = profile or {"account_id": "account-1", "display_name": "Tester"}
        self.exchange_calls: list[dict[str, Any]] = []
        self.closed = False

    def exchange_authorization_code(self, **kwargs: Any) -> SpotifyAccessToken:
        self.exchange_calls.append(kwargs)
        return SpotifyAccessToken(
            access_token="access-token-must-not-persist",
            token_type="Bearer",
            expires_in=3600,
            scope="playlist-modify-private playlist-modify-public",
            refresh_token="refresh-token",
        )

    def get_current_user_profile(self) -> dict[str, Any]:
        return self.profile

    def close(self) -> None:
        self.closed = True


def test_oauth_start_persists_only_hashed_state_and_encrypted_pkce_verifier() -> None:
    now = datetime(2030, 1, 1, 12, tzinfo=UTC)
    repository = InMemoryOAuthStateRepository()
    vault = FakeOAuthVerifierVault()
    state = "state-token-with-at-least-256-bits-of-randomness"
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    service = build_service(
        repository=repository,
        vault=vault,
        now=now,
        state=state,
        verifier=verifier,
    )

    started = service.start(return_to="/discover?source=login")

    parsed = urllib.parse.urlparse(started.authorization_url)
    query = urllib.parse.parse_qs(parsed.query)
    state_hash = hashlib.sha256(state.encode("utf-8")).hexdigest()
    stored = repository.records[state_hash]
    assert query["state"] == [state]
    assert query["code_challenge"] == ["E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["scope"] == ["playlist-modify-private playlist-modify-public"]
    assert stored.state_hash == state_hash
    assert stored.state_hash != state
    assert stored.verifier_ciphertext == b"encrypted-verifier"
    assert verifier.encode("utf-8") not in stored.verifier_ciphertext
    assert stored.return_path == "/discover?source=login"
    assert stored.created_at == now
    assert stored.expires_at == now + timedelta(minutes=10)
    assert vault.encrypt_calls == [(state_hash, verifier)]
    assert state not in repr(started)


def test_oauth_state_is_consumed_once_before_code_exchange() -> None:
    now = datetime(2030, 1, 1, 12, tzinfo=UTC)
    repository = InMemoryOAuthStateRepository()
    vault = FakeOAuthVerifierVault()
    state = "state-token-with-at-least-256-bits-of-randomness"
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    service = build_service(
        repository=repository,
        vault=vault,
        now=now,
        state=state,
        verifier=verifier,
    )
    service.start(return_to="/onboarding/seeds")

    consumed = service.consume_state(state)

    assert consumed.return_path == "/onboarding/seeds"
    assert consumed.code_verifier == verifier
    assert verifier not in repr(consumed)
    with pytest.raises(OAuthStateError, match="invalid or expired"):
        service.consume_state(state)


def test_cancelled_oauth_consumes_state_without_creating_a_spotify_client() -> None:
    now = datetime(2030, 1, 1, 12, tzinfo=UTC)
    repository = InMemoryOAuthStateRepository()
    vault = FakeOAuthVerifierVault()
    oauth = build_service(
        repository=repository,
        vault=vault,
        now=now,
        state="state-token-with-at-least-256-bits-of-randomness",
        verifier="dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk",
    )
    started = oauth.start(return_to="/discover")
    client_calls = 0

    def spotify_client() -> FakeSpotifyOAuthClient:
        nonlocal client_calls
        client_calls += 1
        return FakeSpotifyOAuthClient()

    service = ProductAuthService(
        oauth=oauth,
        sessions=SessionService(repository=InMemorySessionRepository(), now=lambda: now),
        users=InMemoryUserRepository(),
        seeds=FakeSeedRepository(),
        token_vault=vault,
        spotify_client_factory=spotify_client,
        now=lambda: now,
    )

    service.cancel_callback(state=started.state)

    assert client_calls == 0
    with pytest.raises(OAuthStateError, match="invalid or expired"):
        service.cancel_callback(state=started.state)


def test_oauth_state_rejects_expired_value() -> None:
    start_time = datetime(2030, 1, 1, 12, tzinfo=UTC)
    current_time = start_time
    repository = InMemoryOAuthStateRepository()
    vault = FakeOAuthVerifierVault()
    service = OAuthService(
        client_id="client",
        redirect_uri="https://outside-the-loop-beta.vercel.app/api/auth/spotify/callback",
        scopes=("playlist-modify-private",),
        state_repository=repository,
        verifier_vault=vault,
        allowed_return_paths=("/discover",),
        now=lambda: current_time,
        state_factory=lambda: "state-token-with-at-least-256-bits-of-randomness",
        verifier_factory=lambda: "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk",
    )
    started = service.start(return_to="/discover")
    current_time = start_time + timedelta(minutes=11)

    with pytest.raises(OAuthStateError, match="invalid or expired"):
        service.consume_state(started.state)


def test_product_auth_callback_persists_encrypted_refresh_token_and_issues_session() -> None:
    now = datetime(2030, 1, 1, 12, tzinfo=UTC)
    state_repository = InMemoryOAuthStateRepository()
    vault = FakeOAuthVerifierVault()
    oauth = build_service(
        repository=state_repository,
        vault=vault,
        now=now,
        state="state-token-with-at-least-256-bits-of-randomness",
        verifier="dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk",
    )
    started = oauth.start(return_to="/discover")
    users = InMemoryUserRepository(existing_status="approved")
    sessions = SessionService(
        repository=InMemorySessionRepository(),
        now=lambda: now,
        token_factory=iter(("s" * 43, "c" * 43)).__next__,
    )
    spotify = FakeSpotifyOAuthClient()
    service = ProductAuthService(
        oauth=oauth,
        sessions=sessions,
        users=users,
        seeds=FakeSeedRepository(count=1),
        token_vault=vault,
        spotify_client_factory=lambda: spotify,
        now=lambda: now,
    )

    result = service.complete_callback(
        code="authorization-code",
        state=started.state,
    )

    assert result.user.account_id == "account-1"
    assert result.user.access_status == "approved"
    assert result.user.seed_ready is True
    assert result.return_path == "/discover"
    assert result.credentials.record.account_id == "account-1"
    assert spotify.exchange_calls == [
        {
            "code": "authorization-code",
            "redirect_uri": ("https://outside-the-loop-beta.vercel.app/api/auth/spotify/callback"),
            "code_verifier": "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk",
            "required_scopes": ("playlist-modify-private", "playlist-modify-public"),
        }
    ]
    assert vault.refresh_token_call == ("account-1", "refresh-token")
    assert users.upsert_calls[0]["refresh_token_ciphertext"] == b"encrypted-refresh-token"
    assert "access-token-must-not-persist" not in repr(users.upsert_calls)
    assert spotify.closed is True


def test_product_auth_callback_requires_account_id_and_consumes_state_before_failure() -> None:
    now = datetime(2030, 1, 1, 12, tzinfo=UTC)
    state_repository = InMemoryOAuthStateRepository()
    vault = FakeOAuthVerifierVault()
    oauth = build_service(
        repository=state_repository,
        vault=vault,
        now=now,
        state="state-token-with-at-least-256-bits-of-randomness",
        verifier="dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk",
    )
    started = oauth.start(return_to="/discover")
    service = ProductAuthService(
        oauth=oauth,
        sessions=SessionService(repository=InMemorySessionRepository(), now=lambda: now),
        users=InMemoryUserRepository(),
        seeds=FakeSeedRepository(),
        token_vault=vault,
        spotify_client_factory=lambda: FakeSpotifyOAuthClient(
            profile={"id": "legacy-user-id", "display_name": "Tester"}
        ),
        now=lambda: now,
    )

    with pytest.raises(OAuthCallbackError, match="Spotify sign-in could not be completed"):
        service.complete_callback(code="authorization-code", state=started.state)

    with pytest.raises(OAuthStateError, match="invalid or expired"):
        service.complete_callback(code="authorization-code", state=started.state)


def test_product_auth_current_user_returns_only_safe_application_fields() -> None:
    now = datetime(2030, 1, 1, 12, tzinfo=UTC)
    users = InMemoryUserRepository()
    users.records["account-1"] = user_record(
        account_id="account-1",
        access_status="pending",
        display_name="Tester",
        now=now,
        ciphertext=b"secret-ciphertext",
        scopes=("playlist-modify-private",),
    )
    service = ProductAuthService(
        oauth=build_service(
            repository=InMemoryOAuthStateRepository(),
            vault=FakeOAuthVerifierVault(),
            now=now,
            state="state-token-with-at-least-256-bits-of-randomness",
            verifier="dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk",
        ),
        sessions=SessionService(repository=InMemorySessionRepository(), now=lambda: now),
        users=users,
        seeds=FakeSeedRepository(),
        token_vault=FakeOAuthVerifierVault(),
        spotify_client_factory=FakeSpotifyOAuthClient,
        now=lambda: now,
    )
    session = ApplicationSessionRecord(
        session_hash="a" * 64,
        account_id="account-1",
        csrf_hash="b" * 64,
        idle_expires_at=now + timedelta(days=7),
        absolute_expires_at=now + timedelta(days=30),
        last_seen_at=now,
        created_at=now,
    )

    current = service.current_user(session)

    assert current.to_dict() == {
        "account_id": "account-1",
        "display_name": "Tester",
        "access_status": "pending",
        "seed_ready": False,
        "reauthorization_required": False,
    }
    assert "secret-ciphertext" not in repr(current)


@pytest.mark.parametrize(
    "return_to",
    (
        "https://attacker.example/callback",
        "//attacker.example/callback",
        "/unknown",
        "/discover/../settings",
        "/discover#https://attacker.example",
        "/discover\\attacker",
    ),
)
def test_oauth_start_rejects_unsafe_return_paths(return_to: str) -> None:
    service = build_service(
        repository=InMemoryOAuthStateRepository(),
        vault=FakeOAuthVerifierVault(),
        now=datetime(2030, 1, 1, tzinfo=UTC),
        state="state-token-with-at-least-256-bits-of-randomness",
        verifier="dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk",
    )

    with pytest.raises(OAuthReturnPathError, match="return path"):
        service.start(return_to=return_to)


def build_service(
    *,
    repository: InMemoryOAuthStateRepository,
    vault: FakeOAuthVerifierVault,
    now: datetime,
    state: str,
    verifier: str,
) -> OAuthService:
    return OAuthService(
        client_id="client",
        redirect_uri="https://outside-the-loop-beta.vercel.app/api/auth/spotify/callback",
        scopes=("playlist-modify-private", "playlist-modify-public"),
        state_repository=repository,
        verifier_vault=vault,
        allowed_return_paths=("/discover", "/onboarding"),
        now=lambda: now,
        state_factory=lambda: state,
        verifier_factory=lambda: verifier,
    )


def user_record(
    *,
    account_id: str,
    access_status: str,
    display_name: str | None,
    now: datetime,
    ciphertext: bytes,
    scopes: tuple[str, ...],
) -> UserAccountRecord:
    return UserAccountRecord(
        account_id=account_id,
        display_name=display_name,
        access_status=access_status,  # type: ignore[arg-type]
        refresh_token_ciphertext=ciphertext,
        token_scopes=scopes,
        token_issued_at=now,
        reauthorization_required=False,
        last_login_at=now,
        created_at=now,
        updated_at=now,
    )
