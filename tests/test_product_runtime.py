from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast

import pytest

from music_recommender.api.product_runtime import build_product_auth_runtime
from music_recommender.config import load_settings
from music_recommender.storage.postgres import PostgresDatabase


class FakeResult:
    def fetchone(self) -> dict[str, int]:
        return {"ready": 1}


class FakeConnection:
    def execute(self, query: str) -> FakeResult:
        assert query == "select 1 as ready"
        return FakeResult()


class FakeDatabase:
    @contextmanager
    def system_transaction(self) -> Iterator[FakeConnection]:
        yield FakeConnection()


class FakeTokenVault:
    pass


class FakeDiscoveryPublisher:
    def publish(self, **kwargs: str) -> None:
        del kwargs


def test_product_auth_runtime_wires_backend_only_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SPOTIFY_APP_CLIENT_ID", "client")
    monkeypatch.setenv("SPOTIFY_APP_CLIENT_SECRET", "secret")
    monkeypatch.setenv("AUTH_MODE", "hybrid")
    monkeypatch.setenv("RUNTIME_STORE_BACKEND", "supabase")
    monkeypatch.setenv(
        "SUPABASE_DB_URL",
        "postgresql://postgres:postgres@127.0.0.1:55432/postgres",
    )
    monkeypatch.setenv("SPOTIFY_TOKEN_KMS_KEY_ID", "alias/outside-the-loop-spotify")
    monkeypatch.setenv(
        "OBSERVABILITY_HASH_KEY",
        "observability-test-key-that-is-long-enough",
    )
    monkeypatch.setenv("MUSICBRAINZ_CONTACT_EMAIL", "product-owner@example.com")
    monkeypatch.setenv("APP_BASE_URL", "http://localhost:5173")
    monkeypatch.setenv(
        "SPOTIFY_REDIRECT_URI",
        "http://localhost:5173/api/auth/spotify/callback",
    )
    monkeypatch.setenv("AUTH_ALLOWED_ORIGINS", "http://localhost:5173")
    settings = load_settings(env_file=Path("does-not-exist.env"))

    runtime = build_product_auth_runtime(
        settings,
        database=cast(PostgresDatabase, FakeDatabase()),
        token_vault=cast(Any, FakeTokenVault()),
        discovery_publisher=FakeDiscoveryPublisher(),
    )

    assert runtime.auth_service.oauth.scopes == (
        "user-read-private",
        "playlist-modify-private",
        "playlist-modify-public",
    )
    assert runtime.csrf_protection.allowed_origins == frozenset({"http://localhost:5173"})
    assert runtime.discovery_job_service is not None
    assert runtime.observer.user_correlation("account-1")
    assert runtime.ready() is True
