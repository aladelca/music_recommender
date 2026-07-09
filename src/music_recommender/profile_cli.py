from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import uuid4

from music_recommender.config import load_settings
from music_recommender.pipeline.profile import (
    SpotifyProfileExtractionOptions,
    SpotifyProfileExtractor,
)
from music_recommender.sources.spotify_user import SpotifyUserClient, TopTimeRange
from music_recommender.storage.s3 import FileFormat, S3Storage

LOGGER = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract authenticated Spotify profile data.")
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--output", choices=("local", "s3"), default="local")
    parser.add_argument("--local-output-dir", type=Path, default=Path("data/local"))
    parser.add_argument("--file-format", choices=("jsonl", "parquet"), default=None)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--run-date", default=None)
    parser.add_argument("--top-limit", type=int, default=20)
    parser.add_argument("--saved-limit", type=int, default=20)
    parser.add_argument(
        "--top-time-ranges",
        nargs="+",
        choices=("short_term", "medium_term", "long_term"),
        default=["medium_term"],
    )
    parser.add_argument("--include-playlists", action="store_true")
    parser.add_argument("--playlist-limit", type=int, default=10)
    parser.add_argument("--playlist-track-limit", type=int, default=50)
    parser.add_argument("--playlist-id", action="append", dest="playlist_ids", default=[])
    parser.add_argument("--include-recently-played", action="store_true")
    parser.add_argument("--recently-played-limit", type=int, default=20)
    parser.add_argument("--market", default=None)
    parser.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        default="INFO",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(args.log_level)
    settings = load_settings(require_bucket=args.output == "s3" and args.bucket is None)
    if not settings.spotify_user_refresh_token:
        parser.error("SPOTIFY_USER_REFRESH_TOKEN is required for profile extraction")

    run_id = args.run_id or default_run_id()
    run_date = args.run_date or datetime.now(UTC).date().isoformat()
    file_format = args.file_format or settings.output_file_format
    bucket = args.bucket or settings.bucket
    if args.output == "s3" and not bucket:
        parser.error("--bucket or MUSIC_RECOMMENDER_BUCKET is required for --output s3")

    spotify = SpotifyUserClient(
        client_id=settings.spotify_client_id,
        client_secret=settings.spotify_client_secret,
        refresh_token=settings.spotify_user_refresh_token,
    )
    storage = S3Storage(
        bucket=bucket,
        dry_run=args.output == "local",
        local_root=args.local_output_dir / run_id,
    )
    try:
        extractor = SpotifyProfileExtractor(spotify_client=spotify, storage=storage)
        summary = extractor.run(
            SpotifyProfileExtractionOptions(
                run_id=run_id,
                run_date=run_date,
                file_format=cast(FileFormat, file_format),
                top_limit=args.top_limit,
                saved_limit=args.saved_limit,
                top_time_ranges=tuple(cast(TopTimeRange, item) for item in args.top_time_ranges),
                include_playlists=args.include_playlists,
                playlist_limit=args.playlist_limit,
                playlist_track_limit=args.playlist_track_limit,
                playlist_ids=tuple(str(item) for item in args.playlist_ids),
                include_recently_played=args.include_recently_played,
                recently_played_limit=args.recently_played_limit,
                market=args.market or settings.spotify_market,
                required_user_id=settings.spotify_demo_user_id,
            )
        )
    finally:
        spotify.close()

    print(json.dumps(summary.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.INFO if level == "DEBUG" else logging.WARNING)


def default_run_id() -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    return f"profile-{timestamp}-{uuid4().hex[:8]}"


if __name__ == "__main__":
    sys.exit(main())
