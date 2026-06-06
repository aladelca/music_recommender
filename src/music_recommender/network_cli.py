from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import uuid4

from dotenv import load_dotenv

from music_recommender.pipeline.network import NetworkExtractionOptions, NetworkExtractor
from music_recommender.sources.listenbrainz import ListenBrainzDumpReader
from music_recommender.storage.s3 import FileFormat, S3Storage

LOGGER = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract network interaction data.")
    parser.add_argument("--source", choices=("listenbrainz",), default="listenbrainz")
    parser.add_argument("--dump-path", type=Path, default=None)
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--output", choices=("local", "s3"), default="local")
    parser.add_argument("--local-output-dir", type=Path, default=Path("data/local"))
    parser.add_argument("--file-format", choices=("jsonl", "parquet"), default=None)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--run-date", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--user-hash-salt", default=None)
    parser.add_argument(
        "--catalog-tracks-path",
        type=Path,
        default=None,
        help=(
            "Optional local silver/tracks Parquet or JSONL path to link listens to catalog tracks."
        ),
    )
    parser.add_argument(
        "--catalog-run-id",
        default=None,
        help="Optional catalog run id to store in metadata notes.",
    )
    parser.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        default="INFO",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv(".env")
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(args.log_level)

    run_id = args.run_id or default_run_id()
    run_date = args.run_date or datetime.now(UTC).date().isoformat()
    file_format = args.file_format or os.getenv("OUTPUT_FILE_FORMAT", "parquet")
    if file_format not in {"jsonl", "parquet"}:
        parser.error("--file-format or OUTPUT_FILE_FORMAT must be jsonl or parquet")

    dump_path = args.dump_path or _optional_path(os.getenv("LISTENBRAINZ_DUMP_PATH"))
    if dump_path is None:
        parser.error("--dump-path or LISTENBRAINZ_DUMP_PATH is required")
    if not dump_path.exists():
        parser.error(f"ListenBrainz dump path does not exist: {dump_path}")

    bucket = args.bucket or os.getenv("MUSIC_RECOMMENDER_BUCKET")
    if args.output == "s3" and not bucket:
        parser.error("--bucket or MUSIC_RECOMMENDER_BUCKET is required for --output s3")

    LOGGER.info(
        "Starting network extraction run_id=%s source=%s output=%s file_format=%s limit=%s",
        run_id,
        args.source,
        args.output,
        file_format,
        args.limit,
    )
    storage = S3Storage(
        bucket=bucket,
        dry_run=args.output == "local",
        local_root=args.local_output_dir / run_id,
    )
    extractor = NetworkExtractor(listenbrainz=ListenBrainzDumpReader(), storage=storage)
    summary = extractor.run(
        NetworkExtractionOptions(
            dump_path=dump_path,
            run_id=run_id,
            run_date=run_date,
            file_format=cast(FileFormat, file_format),
            user_hash_salt=args.user_hash_salt or os.getenv("LISTENBRAINZ_USER_HASH_SALT", ""),
            limit=args.limit,
            catalog_tracks_path=args.catalog_tracks_path,
            catalog_run_id=args.catalog_run_id,
        )
    )
    print(json.dumps(summary.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


def default_run_id() -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    return f"{timestamp}-{uuid4().hex[:8]}"


def _optional_path(value: str | None) -> Path | None:
    if value is None or not value.strip():
        return None
    return Path(value).expanduser()


if __name__ == "__main__":
    sys.exit(main())
