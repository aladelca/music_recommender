from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, cast
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv

AudioFeatureSource = Literal["none", "reccobeats", "spotify"]
RecommenderDataMode = Literal["local", "s3"]
RecommenderDataRoot = Path | str
OutputFileFormat = Literal["jsonl", "parquet"]
RuntimeStoreBackend = Literal["auto", "local", "dynamodb", "supabase"]
AuthMode = Literal["api_key", "hybrid", "spotify_session"]

_REQUIRED_PRODUCT_SPOTIFY_SCOPES = (
    "user-read-private",
    "playlist-modify-private",
    "playlist-modify-public",
)


@dataclass(frozen=True)
class Settings:
    spotify_client_id: str
    spotify_client_secret: str = field(repr=False)
    openai_api_key: str | None = field(repr=False)
    openai_agent_model: str | None
    aws_region: str
    bucket: str | None
    spotify_market: str
    spotify_redirect_uri: str
    spotify_user_refresh_token: str | None = field(repr=False)
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
    listenbrainz_user_hash_salt: str = field(repr=False)
    recommender_data_root: RecommenderDataRoot
    recommender_data_mode: RecommenderDataMode
    recommender_demo_user_id: str | None
    aws_secrets_prefix: str | None
    runtime_store_backend: RuntimeStoreBackend = "auto"
    users_table_name: str | None = None
    sessions_table_name: str | None = None
    feedback_table_name: str | None = None
    playlists_table_name: str | None = None
    supabase_db_url: str | None = field(default=None, repr=False)
    postgres_pool_min_size: int = 0
    postgres_pool_max_size: int = 4
    postgres_pool_timeout_seconds: float = 5.0
    postgres_statement_timeout_ms: int = 5_000
    spotify_product_scopes: tuple[str, ...] = _REQUIRED_PRODUCT_SPOTIFY_SCOPES
    spotify_token_kms_key_id: str | None = None
    auth_mode: AuthMode = "api_key"
    app_base_url: str | None = None
    auth_allowed_origins: tuple[str, ...] = ()
    musicbrainz_contact_email: str | None = None
    discovery_queue_url: str | None = None
    observability_hash_key: str | None = field(default=None, repr=False)


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


def _get_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return float(value)


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


def _get_list(name: str, default: tuple[str, ...] = ()) -> tuple[str, ...]:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    normalized = value.replace(",", " ")
    return tuple(item for item in normalized.split() if item)


def _validate_postgres_settings(
    *,
    runtime_store_backend: RuntimeStoreBackend,
    database_url: str | None,
    pool_min_size: int,
    pool_max_size: int,
    pool_timeout_seconds: float,
    statement_timeout_ms: int,
) -> None:
    if runtime_store_backend == "supabase" and database_url is None:
        raise ValueError("SUPABASE_DB_URL is required when RUNTIME_STORE_BACKEND=supabase.")
    if database_url is not None:
        parsed = urlparse(database_url)
        if parsed.scheme not in {"postgres", "postgresql"} or not parsed.hostname:
            raise ValueError("SUPABASE_DB_URL must be a valid PostgreSQL connection URL.")
        if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            ssl_modes = parse_qs(parsed.query).get("sslmode", [])
            if not any(mode in {"require", "verify-ca", "verify-full"} for mode in ssl_modes):
                raise ValueError("SUPABASE_DB_URL must require TLS for a remote database.")
    if pool_min_size < 0 or pool_min_size > 10:
        raise ValueError("POSTGRES_POOL_MIN_SIZE must be between 0 and 10.")
    if pool_max_size < 1 or pool_max_size > 20:
        raise ValueError("POSTGRES_POOL_MAX_SIZE must be between 1 and 20.")
    if pool_min_size > pool_max_size:
        raise ValueError("POSTGRES_POOL_MIN_SIZE must not exceed POSTGRES_POOL_MAX_SIZE.")
    if pool_timeout_seconds <= 0 or pool_timeout_seconds > 30:
        raise ValueError("POSTGRES_POOL_TIMEOUT_SECONDS must be greater than 0 and at most 30.")
    if statement_timeout_ms < 100 or statement_timeout_ms > 120_000:
        raise ValueError("POSTGRES_STATEMENT_TIMEOUT_MS must be between 100 and 120000.")


def _validate_product_auth_settings(
    *,
    auth_mode: AuthMode,
    runtime_store_backend: RuntimeStoreBackend,
    token_kms_key_id: str | None,
    app_base_url: str | None,
    redirect_uri: str,
    allowed_origins: tuple[str, ...],
    musicbrainz_contact_email: str | None,
    observability_hash_key: str | None,
    spotify_product_scopes: tuple[str, ...],
) -> None:
    if auth_mode == "api_key":
        return
    if len(spotify_product_scopes) != len(_REQUIRED_PRODUCT_SPOTIFY_SCOPES) or set(
        spotify_product_scopes
    ) != set(_REQUIRED_PRODUCT_SPOTIFY_SCOPES):
        required = ", ".join(_REQUIRED_PRODUCT_SPOTIFY_SCOPES)
        raise ValueError(f"SPOTIFY_PRODUCT_SCOPES must contain only: {required}.")
    if runtime_store_backend != "supabase":
        raise ValueError("RUNTIME_STORE_BACKEND must be supabase for Spotify session auth.")
    if token_kms_key_id is None:
        raise ValueError("SPOTIFY_TOKEN_KMS_KEY_ID is required for Spotify session auth.")
    if observability_hash_key is None or not 32 <= len(observability_hash_key) <= 512:
        raise ValueError(
            "OBSERVABILITY_HASH_KEY must contain between 32 and 512 characters "
            "for Spotify session auth."
        )
    if (
        musicbrainz_contact_email is None
        or "@" not in musicbrainz_contact_email
        or any(character.isspace() for character in musicbrainz_contact_email)
    ):
        raise ValueError("MUSICBRAINZ_CONTACT_EMAIL is required for Spotify session auth.")
    if app_base_url is None:
        raise ValueError("APP_BASE_URL is required for Spotify session auth.")
    app_origin = _normalized_origin(app_base_url, "APP_BASE_URL")
    redirect = urlparse(redirect_uri)
    redirect_origin = _normalized_origin(
        f"{redirect.scheme}://{redirect.netloc}",
        "SPOTIFY_REDIRECT_URI",
    )
    if redirect_origin != app_origin or redirect.path != "/api/auth/spotify/callback":
        raise ValueError(
            "SPOTIFY_REDIRECT_URI must use APP_BASE_URL and /api/auth/spotify/callback."
        )
    if not allowed_origins:
        raise ValueError("AUTH_ALLOWED_ORIGINS is required for Spotify session auth.")
    normalized_origins = tuple(
        _normalized_origin(origin, "AUTH_ALLOWED_ORIGINS") for origin in allowed_origins
    )
    if app_origin not in normalized_origins:
        raise ValueError("AUTH_ALLOWED_ORIGINS must include APP_BASE_URL.")


def _validate_discovery_queue_url(queue_url: str | None) -> None:
    if queue_url is None:
        return
    parsed = urlparse(queue_url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or not parsed.path.endswith(".fifo")
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("DISCOVERY_QUEUE_URL must be a valid HTTPS FIFO SQS URL.")


def _normalized_origin(value: str, name: str) -> str:
    parsed = urlparse(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(f"{name} must contain valid HTTP origins without paths.")
    if parsed.scheme != "https" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError(f"{name} must use HTTPS for non-local origins.")
    host = parsed.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    default_port = 443 if parsed.scheme == "https" else 80
    port = f":{parsed.port}" if parsed.port and parsed.port != default_port else ""
    return f"{parsed.scheme}://{host}{port}"


def load_settings(
    env_file: Path | str = ".env",
    *,
    require_bucket: bool = False,
    require_spotify: bool = True,
) -> Settings:
    env_path = Path(env_file)
    if env_path.exists():
        load_dotenv(env_path)

    spotify_client_id = _first_env("SPOTIFY_APP_CLIENT_ID", "SPOTIFY_CLIENT_ID")
    spotify_client_secret = _first_env("SPOTIFY_APP_CLIENT_SECRET", "SPOTIFY_CLIENT_SECRET")
    if require_spotify and (not spotify_client_id or not spotify_client_secret):
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

    runtime_store_backend = cast(
        RuntimeStoreBackend,
        _get_choice(
            "RUNTIME_STORE_BACKEND",
            "auto",
            {"auto", "local", "dynamodb", "supabase"},
        ),
    )
    supabase_db_url = _get_optional_str("SUPABASE_DB_URL")
    postgres_pool_min_size = _get_int("POSTGRES_POOL_MIN_SIZE", 0)
    postgres_pool_max_size = _get_int("POSTGRES_POOL_MAX_SIZE", 4)
    postgres_pool_timeout_seconds = _get_float("POSTGRES_POOL_TIMEOUT_SECONDS", 5.0)
    postgres_statement_timeout_ms = _get_int("POSTGRES_STATEMENT_TIMEOUT_MS", 5_000)
    auth_mode = cast(
        AuthMode,
        _get_choice(
            "AUTH_MODE",
            "api_key",
            {"api_key", "hybrid", "spotify_session"},
        ),
    )
    spotify_redirect_uri = os.getenv(
        "SPOTIFY_REDIRECT_URI",
        "https://www.google.com/",
    )
    app_base_url = _get_optional_str("APP_BASE_URL")
    auth_allowed_origins = _get_list(
        "AUTH_ALLOWED_ORIGINS",
        (app_base_url,) if app_base_url else (),
    )
    spotify_token_kms_key_id = _get_optional_str("SPOTIFY_TOKEN_KMS_KEY_ID")
    musicbrainz_contact_email = _get_optional_str("MUSICBRAINZ_CONTACT_EMAIL")
    discovery_queue_url = _get_optional_str("DISCOVERY_QUEUE_URL")
    observability_hash_key = _get_optional_str("OBSERVABILITY_HASH_KEY")
    spotify_product_scopes = _get_scopes(
        "SPOTIFY_PRODUCT_SCOPES",
        _REQUIRED_PRODUCT_SPOTIFY_SCOPES,
    )
    _validate_discovery_queue_url(discovery_queue_url)
    _validate_postgres_settings(
        runtime_store_backend=runtime_store_backend,
        database_url=supabase_db_url,
        pool_min_size=postgres_pool_min_size,
        pool_max_size=postgres_pool_max_size,
        pool_timeout_seconds=postgres_pool_timeout_seconds,
        statement_timeout_ms=postgres_statement_timeout_ms,
    )
    _validate_product_auth_settings(
        auth_mode=auth_mode,
        runtime_store_backend=runtime_store_backend,
        token_kms_key_id=spotify_token_kms_key_id,
        app_base_url=app_base_url,
        redirect_uri=spotify_redirect_uri,
        allowed_origins=auth_allowed_origins,
        musicbrainz_contact_email=musicbrainz_contact_email,
        observability_hash_key=observability_hash_key,
        spotify_product_scopes=spotify_product_scopes,
    )

    return Settings(
        spotify_client_id=spotify_client_id or "",
        spotify_client_secret=spotify_client_secret or "",
        openai_api_key=_get_optional_str("OPENAI_API_KEY"),
        openai_agent_model=_get_optional_str("OPENAI_AGENT_MODEL"),
        aws_region=os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1",
        bucket=bucket,
        spotify_market=os.getenv("SPOTIFY_MARKET", "US"),
        spotify_redirect_uri=spotify_redirect_uri,
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
        spotify_product_scopes=spotify_product_scopes,
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
        runtime_store_backend=runtime_store_backend,
        users_table_name=_get_optional_str("USERS_TABLE_NAME"),
        sessions_table_name=_get_optional_str("SESSIONS_TABLE_NAME"),
        feedback_table_name=_get_optional_str("FEEDBACK_TABLE_NAME"),
        playlists_table_name=_get_optional_str("PLAYLISTS_TABLE_NAME"),
        supabase_db_url=supabase_db_url,
        postgres_pool_min_size=postgres_pool_min_size,
        postgres_pool_max_size=postgres_pool_max_size,
        postgres_pool_timeout_seconds=postgres_pool_timeout_seconds,
        postgres_statement_timeout_ms=postgres_statement_timeout_ms,
        spotify_token_kms_key_id=spotify_token_kms_key_id,
        auth_mode=auth_mode,
        app_base_url=app_base_url,
        auth_allowed_origins=auth_allowed_origins,
        musicbrainz_contact_email=musicbrainz_contact_email,
        discovery_queue_url=discovery_queue_url,
        observability_hash_key=observability_hash_key,
    )
