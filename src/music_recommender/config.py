from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv

AudioFeatureSource = Literal["none", "reccobeats", "spotify"]
RecommenderDataMode = Literal["local", "s3"]
RecommenderDataRoot = Path | str
OutputFileFormat = Literal["jsonl", "parquet"]
RuntimeStoreBackend = Literal["auto", "local", "dynamodb"]


@dataclass(frozen=True)
class Settings:
    spotify_client_id: str
    spotify_client_secret: str
    openai_api_key: str | None
    openai_agent_model: str | None
    aws_region: str
    bucket: str | None
    spotify_market: str
    spotify_redirect_uri: str
    spotify_user_refresh_token: str | None
    spotify_demo_user_id: str
    spotify_user_scopes: tuple[str, ...]
    max_tracks_per_artist: int
    enable_spotify_audio_features: bool
    audio_feature_source: AudioFeatureSource
    output_file_format: OutputFileFormat
    enable_lyrics_nlp: bool
    lyrics_language_model: str
    lyrics_language_model_path: Path | None
    lyrics_sentiment_model: str
    lyrics_nlp_batch_size: int
    listenbrainz_dump_path: Path | None
    listenbrainz_user_hash_salt: str
    recommender_data_root: RecommenderDataRoot
    recommender_data_mode: RecommenderDataMode
    recommender_demo_user_id: str | None
    aws_secrets_prefix: str | None
    runtime_store_backend: RuntimeStoreBackend = "auto"
    users_table_name: str | None = None
    sessions_table_name: str | None = None
    feedback_table_name: str | None = None
    playlists_table_name: str | None = None


def _get_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _get_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return int(value)


def _first_env(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return None


def _get_choice[ChoiceT: str](name: str, default: ChoiceT, choices: set[ChoiceT]) -> ChoiceT:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    normalized = value.strip().lower()
    if normalized not in choices:
        allowed = ", ".join(sorted(choices))
        raise ValueError(f"{name} must be one of: {allowed}")
    return normalized


def _get_optional_path(name: str) -> Path | None:
    value = os.getenv(name)
    if value is None or not value.strip():
        return None
    return Path(value).expanduser()


def _get_optional_str(name: str) -> str | None:
    value = os.getenv(name)
    if value is None or not value.strip():
        return None
    return value.strip()


def _get_path(name: str, default: str) -> Path:
    value = os.getenv(name)
    if value is None or not value.strip():
        return Path(default)
    return Path(value).expanduser()


def _get_recommender_data_root(name: str, default: str) -> RecommenderDataRoot:
    value = os.getenv(name)
    if value is None or not value.strip():
        return Path(default)
    normalized = value.strip()
    if normalized.startswith("s3://"):
        return normalized.rstrip("/")
    return Path(normalized).expanduser()


def _get_scopes(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    normalized = value.replace(",", " ")
    return tuple(scope.strip() for scope in normalized.split() if scope.strip())


def load_settings(env_file: Path | str = ".env", *, require_bucket: bool = False) -> Settings:
    env_path = Path(env_file)
    if env_path.exists():
        load_dotenv(env_path)

    spotify_client_id = _first_env("SPOTIFY_APP_CLIENT_ID", "SPOTIFY_CLIENT_ID")
    spotify_client_secret = _first_env("SPOTIFY_APP_CLIENT_SECRET", "SPOTIFY_CLIENT_SECRET")
    if not spotify_client_id or not spotify_client_secret:
        raise ValueError(
            "Missing Spotify credentials. Set SPOTIFY_APP_CLIENT_ID and "
            "SPOTIFY_APP_CLIENT_SECRET in .env."
        )

    bucket = os.getenv("MUSIC_RECOMMENDER_BUCKET") or None
    if require_bucket and not bucket:
        raise ValueError("Missing MUSIC_RECOMMENDER_BUCKET for S3 upload mode.")

    max_tracks = _get_int("MAX_TRACKS_PER_ARTIST", 150)
    if max_tracks < 1 or max_tracks > 150:
        raise ValueError("MAX_TRACKS_PER_ARTIST must be between 1 and 150.")

    return Settings(
        spotify_client_id=spotify_client_id,
        spotify_client_secret=spotify_client_secret,
        openai_api_key=_get_optional_str("OPENAI_API_KEY"),
        openai_agent_model=_get_optional_str("OPENAI_AGENT_MODEL"),
        aws_region=os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1",
        bucket=bucket,
        spotify_market=os.getenv("SPOTIFY_MARKET", "US"),
        spotify_redirect_uri=os.getenv(
            "SPOTIFY_REDIRECT_URI",
            "https://www.google.com/",
        ),
        spotify_user_refresh_token=_get_optional_str("SPOTIFY_USER_REFRESH_TOKEN"),
        spotify_demo_user_id=os.getenv("SPOTIFY_DEMO_USER_ID", "12175364859"),
        spotify_user_scopes=_get_scopes(
            "SPOTIFY_USER_SCOPES",
            (
                "user-top-read",
                "user-library-read",
                "playlist-read-private",
                "playlist-modify-private",
                "playlist-modify-public",
            ),
        ),
        max_tracks_per_artist=max_tracks,
        enable_spotify_audio_features=_get_bool("ENABLE_SPOTIFY_AUDIO_FEATURES"),
        audio_feature_source=_get_choice(
            "AUDIO_FEATURE_SOURCE",
            "reccobeats",
            {"none", "reccobeats", "spotify"},
        ),
        output_file_format=_get_choice("OUTPUT_FILE_FORMAT", "parquet", {"jsonl", "parquet"}),
        enable_lyrics_nlp=_get_bool("ENABLE_LYRICS_NLP"),
        lyrics_language_model=os.getenv("LYRICS_LANGUAGE_MODEL", "fasttext-lid-176"),
        lyrics_language_model_path=_get_optional_path("LYRICS_LANGUAGE_MODEL_PATH"),
        lyrics_sentiment_model=os.getenv(
            "LYRICS_SENTIMENT_MODEL",
            "cardiffnlp/twitter-xlm-roberta-base-sentiment-multilingual",
        ),
        lyrics_nlp_batch_size=_get_int("LYRICS_NLP_BATCH_SIZE", 8),
        listenbrainz_dump_path=_get_optional_path("LISTENBRAINZ_DUMP_PATH"),
        listenbrainz_user_hash_salt=os.getenv("LISTENBRAINZ_USER_HASH_SALT", ""),
        recommender_data_root=_get_recommender_data_root("RECOMMENDER_DATA_ROOT", "data/local"),
        recommender_data_mode=_get_choice("RECOMMENDER_DATA_MODE", "local", {"local", "s3"}),
        recommender_demo_user_id=_get_optional_str("RECOMMENDER_DEMO_USER_ID"),
        aws_secrets_prefix=_get_optional_str("AWS_SECRETS_PREFIX"),
        runtime_store_backend=_get_choice(
            "RUNTIME_STORE_BACKEND",
            "auto",
            {"auto", "local", "dynamodb"},
        ),
        users_table_name=_get_optional_str("USERS_TABLE_NAME"),
        sessions_table_name=_get_optional_str("SESSIONS_TABLE_NAME"),
        feedback_table_name=_get_optional_str("FEEDBACK_TABLE_NAME"),
        playlists_table_name=_get_optional_str("PLAYLISTS_TABLE_NAME"),
    )
