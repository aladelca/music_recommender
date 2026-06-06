from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from music_recommender.config import load_settings
from music_recommender.nlp.lyrics import LyricsNlpProcessor
from music_recommender.pipeline.extract import DataExtractor, ExtractionOptions
from music_recommender.sources.lrclib import LrcLibClient
from music_recommender.sources.lyrics_ovh import LyricsOvhClient
from music_recommender.sources.reccobeats import ReccoBeatsClient
from music_recommender.sources.spotify import SpotifyClient
from music_recommender.storage.s3 import S3Storage

LOGGER = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract music catalog and lyrics data.")
    parser.add_argument("--seeds", type=Path, default=Path("docs/base.md"))
    parser.add_argument("--aliases", type=Path, default=Path("config/artist_aliases.yml"))
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--output", choices=("local", "s3"), default="local")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Alias for --output local. APIs are still called; outputs are written locally.",
    )
    parser.add_argument("--local-output-dir", type=Path, default=Path("data/local"))
    parser.add_argument("--max-tracks-per-artist", type=int, default=None)
    parser.add_argument("--market", default=None)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--run-date", default=None)
    parser.add_argument("--enable-audio-features", action="store_true")
    parser.add_argument(
        "--audio-feature-source",
        choices=("none", "reccobeats", "spotify"),
        default=None,
        help="Audio feature source. Defaults to AUDIO_FEATURE_SOURCE or reccobeats.",
    )
    parser.add_argument(
        "--file-format",
        choices=("jsonl", "parquet"),
        default=None,
        help="Data table format. Run metadata remains JSON.",
    )
    parser.add_argument("--enable-lyrics-nlp", action="store_true")
    parser.add_argument("--language-model", default=None)
    parser.add_argument("--language-model-path", type=Path, default=None)
    parser.add_argument("--sentiment-model", default=None)
    parser.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        default="INFO",
        help="Logging verbosity for extraction progress.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(args.log_level)
    output_mode = "local" if args.dry_run else args.output
    settings = load_settings(require_bucket=output_mode == "s3" and args.bucket is None)

    max_tracks = args.max_tracks_per_artist or settings.max_tracks_per_artist
    if max_tracks < 1 or max_tracks > 150:
        parser.error("--max-tracks-per-artist must be between 1 and 150")

    run_id = args.run_id or default_run_id()
    run_date = args.run_date or datetime.now(UTC).date().isoformat()
    bucket = args.bucket or settings.bucket
    if output_mode == "s3" and not bucket:
        parser.error("--bucket or MUSIC_RECOMMENDER_BUCKET is required for --output s3")

    audio_feature_source = args.audio_feature_source or settings.audio_feature_source
    if args.enable_audio_features and args.audio_feature_source is None:
        audio_feature_source = "spotify"
    file_format = args.file_format or settings.output_file_format
    enable_lyrics_nlp = args.enable_lyrics_nlp or settings.enable_lyrics_nlp

    LOGGER.info(
        "Starting extraction run_id=%s output=%s seeds=%s max_tracks_per_artist=%s "
        "market=%s audio_feature_source=%s file_format=%s lyrics_nlp=%s",
        run_id,
        output_mode,
        args.seeds,
        max_tracks,
        args.market or settings.spotify_market,
        audio_feature_source,
        file_format,
        enable_lyrics_nlp,
    )
    if output_mode == "s3":
        LOGGER.info("Writing outputs to s3://%s", bucket)
    else:
        LOGGER.info("Writing outputs locally under %s", args.local_output_dir / run_id)

    spotify = SpotifyClient(
        client_id=settings.spotify_client_id,
        client_secret=settings.spotify_client_secret,
        market=args.market or settings.spotify_market,
    )
    lrclib = LrcLibClient()
    lyrics_ovh = LyricsOvhClient()
    reccobeats = ReccoBeatsClient() if audio_feature_source == "reccobeats" else None
    lyrics_nlp = (
        LyricsNlpProcessor.default(
            language_model=args.language_model or settings.lyrics_language_model,
            language_model_path=args.language_model_path or settings.lyrics_language_model_path,
            sentiment_model=args.sentiment_model or settings.lyrics_sentiment_model,
            batch_size=settings.lyrics_nlp_batch_size,
        )
        if enable_lyrics_nlp
        else None
    )
    storage = S3Storage(
        bucket=bucket,
        dry_run=output_mode == "local",
        local_root=args.local_output_dir / run_id,
    )

    try:
        extractor = DataExtractor(
            spotify=spotify,
            lrclib=lrclib,
            lyrics_ovh=lyrics_ovh,
            storage=storage,
            reccobeats=reccobeats,
            lyrics_nlp=lyrics_nlp,
        )
        summary = extractor.run(
            ExtractionOptions(
                seeds_path=args.seeds,
                aliases_path=args.aliases,
                run_id=run_id,
                run_date=run_date,
                max_tracks_per_artist=max_tracks,
                enable_audio_features=(
                    args.enable_audio_features or settings.enable_spotify_audio_features
                ),
                audio_feature_source=audio_feature_source,
                file_format=file_format,
                enable_lyrics_nlp=enable_lyrics_nlp,
            )
        )
    finally:
        spotify.close()
        lrclib.close()
        lyrics_ovh.close()
        if reccobeats is not None:
            reccobeats.close()

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
    return f"{timestamp}-{uuid4().hex[:8]}"


if __name__ == "__main__":
    sys.exit(main())
