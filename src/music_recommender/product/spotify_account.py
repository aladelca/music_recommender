from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol

from music_recommender.sources.spotify_user import SpotifyUserClient
from music_recommender.storage.protocols import UserAccountRecord


class SpotifyAccountUnavailableError(RuntimeError):
    pass


class SpotifyAccountUserRepository(Protocol):
    def get(self, *, account_id: str) -> UserAccountRecord | None: ...

    def replace_refresh_token(
        self,
        *,
        account_id: str,
        refresh_token_ciphertext: bytes,
        token_scopes: tuple[str, ...],
        token_issued_at: datetime,
    ) -> UserAccountRecord: ...


class SpotifyRefreshTokenVault(Protocol):
    def decrypt_refresh_token(self, *, account_id: str, ciphertext: bytes) -> str: ...

    def encrypt_refresh_token(self, *, account_id: str, refresh_token: str) -> bytes: ...


class AccountSpotifyClientFactory:
    def __init__(
        self,
        *,
        users: SpotifyAccountUserRepository,
        token_vault: SpotifyRefreshTokenVault,
        client_id: str,
        client_secret: str,
        client_factory: Callable[..., Any] = SpotifyUserClient,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.users = users
        self.token_vault = token_vault
        self.client_id = client_id
        self.client_secret = client_secret
        self.client_factory = client_factory
        self.now = now or (lambda: datetime.now(UTC))

    def create(self, *, account_id: str) -> Any:
        user = self.users.get(account_id=account_id)
        if (
            user is None
            or user.access_status != "approved"
            or user.reauthorization_required
            or user.refresh_token_ciphertext is None
        ):
            raise SpotifyAccountUnavailableError(
                "Spotify reconnection is required for this account."
            )
        refresh_token = self.token_vault.decrypt_refresh_token(
            account_id=account_id,
            ciphertext=user.refresh_token_ciphertext,
        )

        def refresh_token_updated(rotated_token: str) -> None:
            ciphertext = self.token_vault.encrypt_refresh_token(
                account_id=account_id,
                refresh_token=rotated_token,
            )
            self.users.replace_refresh_token(
                account_id=account_id,
                refresh_token_ciphertext=ciphertext,
                token_scopes=user.token_scopes,
                token_issued_at=_aware_utc(self.now()),
            )

        return self.client_factory(
            client_id=self.client_id,
            client_secret=self.client_secret,
            refresh_token=refresh_token,
            refresh_token_updated=refresh_token_updated,
            request_timeout_seconds=4.0,
            request_max_retries=0,
        )


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Spotify account timestamps must be timezone-aware.")
    return value.astimezone(UTC)
