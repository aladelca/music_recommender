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
