from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from music_recommender.product.spotify_account import (
    AccountSpotifyClientFactory,
    SpotifyAccountUnavailableError,
)
from music_recommender.storage.protocols import UserAccountRecord


class FakeUsers:
    def __init__(self, user: UserAccountRecord) -> None:
        self.user = user
        self.replacements: list[dict[str, Any]] = []

    def get(self, *, account_id: str) -> UserAccountRecord | None:
        return self.user if account_id == self.user.account_id else None

    def replace_refresh_token(self, **kwargs: Any) -> UserAccountRecord:
        self.replacements.append(kwargs)
        self.user = replace(
            self.user,
            refresh_token_ciphertext=kwargs["refresh_token_ciphertext"],
            token_issued_at=kwargs["token_issued_at"],
        )
        return self.user


class FakeVault:
    def __init__(self) -> None:
        self.decrypt_calls: list[dict[str, Any]] = []
        self.encrypt_calls: list[dict[str, Any]] = []

    def decrypt_refresh_token(self, **kwargs: Any) -> str:
        self.decrypt_calls.append(kwargs)
        return "plaintext-refresh-token"

    def encrypt_refresh_token(self, **kwargs: Any) -> bytes:
        self.encrypt_calls.append(kwargs)
        return b"rotated-ciphertext"


def test_account_spotify_client_decrypts_for_current_account_and_persists_rotation() -> None:
    now = datetime(2030, 1, 1, tzinfo=UTC)
    users = FakeUsers(user(now))
    vault = FakeVault()
    client_arguments: dict[str, Any] = {}

    def build_client(**kwargs: Any) -> object:
        client_arguments.update(kwargs)
        return object()

    factory = AccountSpotifyClientFactory(
        users=users,
        token_vault=vault,
        client_id="client",
        client_secret="secret",
        client_factory=build_client,
        now=lambda: now,
    )

    factory.create(account_id="account-1")
    client_arguments["refresh_token_updated"]("rotated-refresh-token")

    assert vault.decrypt_calls == [{"account_id": "account-1", "ciphertext": b"encrypted-token"}]
    assert client_arguments["refresh_token"] == "plaintext-refresh-token"
    assert vault.encrypt_calls == [
        {"account_id": "account-1", "refresh_token": "rotated-refresh-token"}
    ]
    assert users.replacements[0]["refresh_token_ciphertext"] == b"rotated-ciphertext"
    assert "plaintext-refresh-token" not in repr(factory)


def test_account_spotify_client_fails_closed_when_reconnect_is_required() -> None:
    now = datetime(2030, 1, 1, tzinfo=UTC)
    users = FakeUsers(replace(user(now), reauthorization_required=True))
    factory = AccountSpotifyClientFactory(
        users=users,
        token_vault=FakeVault(),
        client_id="client",
        client_secret="secret",
        client_factory=lambda **kwargs: kwargs,
    )

    with pytest.raises(SpotifyAccountUnavailableError, match="reconnection"):
        factory.create(account_id="account-1")


def user(now: datetime) -> UserAccountRecord:
    return UserAccountRecord(
        account_id="account-1",
        display_name="Tester",
        access_status="approved",
        refresh_token_ciphertext=b"encrypted-token",
        token_scopes=("playlist-modify-public",),
        token_issued_at=now,
        reauthorization_required=False,
        last_login_at=now,
        created_at=now,
        updated_at=now,
    )
