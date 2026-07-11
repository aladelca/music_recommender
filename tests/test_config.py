from __future__ import annotations

from pathlib import Path

import pytest

from music_recommender.config import load_settings


def test_load_settings_includes_demo_readiness_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPOTIFY_APP_CLIENT_ID", "client")
    monkeypatch.setenv("SPOTIFY_APP_CLIENT_SECRET", "secret")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_AGENT_MODEL", raising=False)
    monkeypatch.delenv("SPOTIFY_REDIRECT_URI", raising=False)
    monkeypatch.delenv("SPOTIFY_USER_REFRESH_TOKEN", raising=False)
    monkeypatch.delenv("RECOMMENDER_DATA_ROOT", raising=False)
    monkeypatch.delenv("RECOMMENDER_DATA_MODE", raising=False)
    monkeypatch.delenv("RECOMMENDER_DEMO_USER_ID", raising=False)

    settings = load_settings(env_file=Path("does-not-exist.env"))

    assert settings.openai_api_key is None
    assert settings.openai_agent_model is None
    assert settings.spotify_redirect_uri == "https://www.google.com/"
    assert settings.spotify_user_refresh_token is None
    assert settings.spotify_demo_user_id == "12175364859"
    assert settings.spotify_user_scopes == (
        "user-top-read",
        "user-library-read",
        "playlist-read-private",
        "playlist-modify-private",
        "playlist-modify-public",
    )
    assert settings.recommender_data_root == Path("data/local")
    assert settings.recommender_data_mode == "local"


def test_load_settings_validates_recommender_data_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPOTIFY_APP_CLIENT_ID", "client")
    monkeypatch.setenv("SPOTIFY_APP_CLIENT_SECRET", "secret")
    monkeypatch.setenv("RECOMMENDER_DATA_MODE", "database")

    with pytest.raises(ValueError, match="RECOMMENDER_DATA_MODE"):
        load_settings(env_file=Path("does-not-exist.env"))


def test_load_settings_preserves_s3_recommender_data_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SPOTIFY_APP_CLIENT_ID", "client")
    monkeypatch.setenv("SPOTIFY_APP_CLIENT_SECRET", "secret")
    monkeypatch.setenv("RECOMMENDER_DATA_MODE", "s3")
    monkeypatch.setenv("RECOMMENDER_DATA_ROOT", "s3://music-recommender-demo/")

    settings = load_settings(env_file=Path("does-not-exist.env"))

    assert settings.recommender_data_mode == "s3"
    assert settings.recommender_data_root == "s3://music-recommender-demo"


def test_load_settings_parses_scope_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPOTIFY_APP_CLIENT_ID", "client")
    monkeypatch.setenv("SPOTIFY_APP_CLIENT_SECRET", "secret")
    monkeypatch.setenv("SPOTIFY_USER_SCOPES", "user-top-read, playlist-modify-private")

    settings = load_settings(env_file=Path("does-not-exist.env"))

    assert settings.spotify_user_scopes == ("user-top-read", "playlist-modify-private")


def test_load_settings_accepts_backend_only_supabase_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SPOTIFY_APP_CLIENT_ID", "client")
    monkeypatch.setenv("SPOTIFY_APP_CLIENT_SECRET", "secret")
    monkeypatch.setenv("RUNTIME_STORE_BACKEND", "supabase")
    monkeypatch.setenv(
        "SUPABASE_DB_URL",
        "postgresql://backend:super-secret@127.0.0.1:55432/postgres",
    )
    monkeypatch.setenv("SPOTIFY_TOKEN_KMS_KEY_ID", "alias/outside-the-loop-spotify")
    monkeypatch.setenv(
        "OBSERVABILITY_HASH_KEY",
        "observability-test-key-that-is-long-enough",
    )
    monkeypatch.setenv("MUSICBRAINZ_CONTACT_EMAIL", "product-owner@example.com")
    monkeypatch.setenv(
        "DISCOVERY_QUEUE_URL",
        "https://sqs.us-east-1.amazonaws.com/123/discovery.fifo",
    )
    monkeypatch.delenv("POSTGRES_POOL_MIN_SIZE", raising=False)
    monkeypatch.delenv("POSTGRES_POOL_MAX_SIZE", raising=False)
    monkeypatch.delenv("POSTGRES_POOL_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("POSTGRES_STATEMENT_TIMEOUT_MS", raising=False)

    settings = load_settings(env_file=Path("does-not-exist.env"))

    assert settings.runtime_store_backend == "supabase"
    assert settings.supabase_db_url == (
        "postgresql://backend:super-secret@127.0.0.1:55432/postgres"
    )
    assert settings.postgres_pool_min_size == 0
    assert settings.postgres_pool_max_size == 4
    assert settings.postgres_pool_timeout_seconds == 5.0
    assert settings.postgres_statement_timeout_ms == 5_000
    assert settings.spotify_product_scopes == (
        "user-read-private",
        "playlist-modify-private",
        "playlist-modify-public",
    )
    assert settings.spotify_token_kms_key_id == "alias/outside-the-loop-spotify"
    assert settings.auth_mode == "api_key"
    assert settings.app_base_url is None
    assert settings.auth_allowed_origins == ()
    assert settings.discovery_queue_url == (
        "https://sqs.us-east-1.amazonaws.com/123/discovery.fifo"
    )
    assert "super-secret" not in repr(settings)


def test_load_settings_accepts_spotify_session_product_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SPOTIFY_APP_CLIENT_ID", "client")
    monkeypatch.setenv("SPOTIFY_APP_CLIENT_SECRET", "secret")
    monkeypatch.setenv("AUTH_MODE", "hybrid")
    monkeypatch.setenv("RUNTIME_STORE_BACKEND", "supabase")
    monkeypatch.setenv(
        "SUPABASE_DB_URL",
        "postgresql://backend:secret@db.example.test:5432/postgres?sslmode=require",
    )
    monkeypatch.setenv("SPOTIFY_TOKEN_KMS_KEY_ID", "alias/outside-the-loop-spotify")
    monkeypatch.setenv(
        "OBSERVABILITY_HASH_KEY",
        "observability-test-key-that-is-long-enough",
    )
    monkeypatch.setenv("MUSICBRAINZ_CONTACT_EMAIL", "product-owner@example.com")
    monkeypatch.setenv("APP_BASE_URL", "https://outside-the-loop-beta.vercel.app")
    monkeypatch.setenv(
        "SPOTIFY_REDIRECT_URI",
        "https://outside-the-loop-beta.vercel.app/api/auth/spotify/callback",
    )
    monkeypatch.setenv(
        "AUTH_ALLOWED_ORIGINS",
        "https://outside-the-loop-beta.vercel.app,http://localhost:5173",
    )

    settings = load_settings(env_file=Path("does-not-exist.env"))

    assert settings.auth_mode == "hybrid"
    assert settings.app_base_url == "https://outside-the-loop-beta.vercel.app"
    assert settings.auth_allowed_origins == (
        "https://outside-the-loop-beta.vercel.app",
        "http://localhost:5173",
    )
    assert settings.musicbrainz_contact_email == "product-owner@example.com"
    assert settings.observability_hash_key == "observability-test-key-that-is-long-enough"
    assert "observability-test-key" not in repr(settings)


@pytest.mark.parametrize(
    "spotify_product_scopes",
    (
        "playlist-modify-private playlist-modify-public",
        "user-read-private playlist-modify-private playlist-modify-public user-top-read",
    ),
)
def test_load_settings_rejects_unapproved_product_scopes(
    monkeypatch: pytest.MonkeyPatch,
    spotify_product_scopes: str,
) -> None:
    monkeypatch.setenv("SPOTIFY_APP_CLIENT_ID", "client")
    monkeypatch.setenv("SPOTIFY_APP_CLIENT_SECRET", "secret")
    monkeypatch.setenv("AUTH_MODE", "spotify_session")
    monkeypatch.setenv("RUNTIME_STORE_BACKEND", "supabase")
    monkeypatch.setenv(
        "SUPABASE_DB_URL",
        "postgresql://backend:secret@db.example.test:5432/postgres?sslmode=require",
    )
    monkeypatch.setenv("SPOTIFY_TOKEN_KMS_KEY_ID", "alias/outside-the-loop-spotify")
    monkeypatch.setenv(
        "OBSERVABILITY_HASH_KEY",
        "observability-test-key-that-is-long-enough",
    )
    monkeypatch.setenv("MUSICBRAINZ_CONTACT_EMAIL", "product-owner@example.com")
    monkeypatch.setenv("APP_BASE_URL", "https://outside-the-loop-beta.vercel.app")
    monkeypatch.setenv(
        "SPOTIFY_REDIRECT_URI",
        "https://outside-the-loop-beta.vercel.app/api/auth/spotify/callback",
    )
    monkeypatch.setenv("AUTH_ALLOWED_ORIGINS", "https://outside-the-loop-beta.vercel.app")
    monkeypatch.setenv(
        "SPOTIFY_PRODUCT_SCOPES",
        spotify_product_scopes,
    )

    with pytest.raises(ValueError, match="user-read-private"):
        load_settings(env_file=Path("does-not-exist.env"))


def test_load_settings_rejects_missing_product_observability_hash_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SPOTIFY_APP_CLIENT_ID", "client")
    monkeypatch.setenv("SPOTIFY_APP_CLIENT_SECRET", "secret")
    monkeypatch.setenv("AUTH_MODE", "hybrid")
    monkeypatch.setenv("RUNTIME_STORE_BACKEND", "supabase")
    monkeypatch.setenv(
        "SUPABASE_DB_URL",
        "postgresql://backend:secret@db.example.test:5432/postgres?sslmode=require",
    )
    monkeypatch.setenv("SPOTIFY_TOKEN_KMS_KEY_ID", "alias/outside-the-loop-spotify")
    monkeypatch.setenv("MUSICBRAINZ_CONTACT_EMAIL", "product-owner@example.com")
    monkeypatch.setenv("APP_BASE_URL", "https://outside-the-loop-beta.vercel.app")
    monkeypatch.setenv(
        "SPOTIFY_REDIRECT_URI",
        "https://outside-the-loop-beta.vercel.app/api/auth/spotify/callback",
    )
    monkeypatch.setenv("AUTH_ALLOWED_ORIGINS", "https://outside-the-loop-beta.vercel.app")
    monkeypatch.delenv("OBSERVABILITY_HASH_KEY", raising=False)

    with pytest.raises(ValueError, match="OBSERVABILITY_HASH_KEY"):
        load_settings(env_file=Path("does-not-exist.env"))


@pytest.mark.parametrize("auth_mode", ("open", "oauth", "session"))
def test_load_settings_rejects_unknown_auth_mode(
    monkeypatch: pytest.MonkeyPatch,
    auth_mode: str,
) -> None:
    monkeypatch.setenv("SPOTIFY_APP_CLIENT_ID", "client")
    monkeypatch.setenv("SPOTIFY_APP_CLIENT_SECRET", "secret")
    monkeypatch.setenv("AUTH_MODE", auth_mode)

    with pytest.raises(ValueError, match="AUTH_MODE"):
        load_settings(env_file=Path("does-not-exist.env"))


def test_load_settings_requires_complete_product_auth_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SPOTIFY_APP_CLIENT_ID", "client")
    monkeypatch.setenv("SPOTIFY_APP_CLIENT_SECRET", "secret")
    monkeypatch.setenv("AUTH_MODE", "spotify_session")
    monkeypatch.setenv("RUNTIME_STORE_BACKEND", "supabase")
    monkeypatch.setenv(
        "SUPABASE_DB_URL",
        "postgresql://backend:secret@db.example.test:5432/postgres?sslmode=require",
    )
    monkeypatch.delenv("SPOTIFY_TOKEN_KMS_KEY_ID", raising=False)
    monkeypatch.delenv("APP_BASE_URL", raising=False)
    monkeypatch.delenv("AUTH_ALLOWED_ORIGINS", raising=False)

    with pytest.raises(ValueError, match="SPOTIFY_TOKEN_KMS_KEY_ID"):
        load_settings(env_file=Path("does-not-exist.env"))


def test_load_settings_requires_database_url_for_supabase_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SPOTIFY_APP_CLIENT_ID", "client")
    monkeypatch.setenv("SPOTIFY_APP_CLIENT_SECRET", "secret")
    monkeypatch.setenv("RUNTIME_STORE_BACKEND", "supabase")
    monkeypatch.delenv("SUPABASE_DB_URL", raising=False)

    with pytest.raises(
        ValueError,
        match="SUPABASE_DB_URL is required when RUNTIME_STORE_BACKEND=supabase",
    ):
        load_settings(env_file=Path("does-not-exist.env"))


def test_load_settings_requires_tls_for_remote_supabase_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SPOTIFY_APP_CLIENT_ID", "client")
    monkeypatch.setenv("SPOTIFY_APP_CLIENT_SECRET", "secret")
    monkeypatch.setenv("RUNTIME_STORE_BACKEND", "supabase")
    monkeypatch.setenv(
        "SUPABASE_DB_URL",
        "postgresql://backend:super-secret@db.example.test:5432/postgres",
    )

    with pytest.raises(ValueError, match="SUPABASE_DB_URL must require TLS") as error:
        load_settings(env_file=Path("does-not-exist.env"))

    assert "super-secret" not in str(error.value)


def test_load_settings_validates_postgres_pool_bounds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPOTIFY_APP_CLIENT_ID", "client")
    monkeypatch.setenv("SPOTIFY_APP_CLIENT_SECRET", "secret")
    monkeypatch.setenv("RUNTIME_STORE_BACKEND", "supabase")
    monkeypatch.setenv(
        "SUPABASE_DB_URL",
        "postgresql://backend:secret@127.0.0.1:55432/postgres",
    )
    monkeypatch.setenv("POSTGRES_POOL_MIN_SIZE", "5")
    monkeypatch.setenv("POSTGRES_POOL_MAX_SIZE", "4")

    with pytest.raises(ValueError, match="POSTGRES_POOL_MIN_SIZE"):
        load_settings(env_file=Path("does-not-exist.env"))
