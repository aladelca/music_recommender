from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv

AudioFeatureSource = Literal["none", "reccobeats", "spotify"]
OutputFileFormat = Literal["jsonl", "parquet"]


@dataclass(frozen=True)
class Settings:
    spotify_client_id: str
    spotify_client_secret: str
    aws_region: str
    bucket: str | None
    spotify_market: str
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
        aws_region=os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1",
        bucket=bucket,
        spotify_market=os.getenv("SPOTIFY_MARKET", "US"),
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
    )
