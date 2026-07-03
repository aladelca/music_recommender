from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path

from dotenv import load_dotenv

from music_recommender.agents.intent import ParsedMoodIntent, parse_intent_with_agent
from music_recommender.agents.orchestrator import AgenticRecommendationService
from music_recommender.recommender.catalog import load_recommender_catalog_from_run
from music_recommender.recommender.models import UserTasteProfile


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run agentic recommender demo commands.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    recommend = subparsers.add_parser(
        "recommend",
        help="Return catalog-backed recommendations for a natural-language prompt.",
    )
    recommend.add_argument("--prompt", required=True)
    recommend.add_argument("--data-root", default=None)
    recommend.add_argument("--data-mode", choices=("local", "s3"), default=None)
    recommend.add_argument("--catalog-run-id", required=True)
    recommend.add_argument("--interaction-run-id", default=None)
    recommend.add_argument("--limit", type=int, default=10)
    recommend.add_argument("--demo-user-id", default=os.getenv("RECOMMENDER_DEMO_USER_ID", "demo"))
    recommend.add_argument("--liked-artist", action="append", default=[])
    recommend.add_argument("--liked-track-id", action="append", default=[])
    recommend.add_argument("--known-track-id", action="append", default=[])
    recommend.add_argument("--blocked-artist", action="append", default=[])
    recommend.add_argument("--create-playlist", action="store_true")
    recommend.add_argument(
        "--use-openai-agent",
        action="store_true",
        help="Use the OpenAI Agents SDK for intent parsing. Defaults to deterministic parsing.",
    )
    recommend.add_argument("--openai-model", default=os.getenv("OPENAI_AGENT_MODEL"))
    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv(".env")
    parser = build_parser()
    args = parser.parse_args(argv)
    command = str(args.command)
    if command == "recommend":
        return _recommend(args)
    parser.error(f"Unknown command: {command}")


def _recommend(args: argparse.Namespace) -> int:
    data_root = args.data_root or os.getenv("RECOMMENDER_DATA_ROOT", "data/local")
    catalog = load_recommender_catalog_from_run(
        _data_root_value(data_root, args.data_mode),
        catalog_run_id=str(args.catalog_run_id),
        interaction_run_id=args.interaction_run_id,
        data_mode=args.data_mode,
    )
    profile = UserTasteProfile(
        user_id=str(args.demo_user_id),
        liked_track_ids=tuple(str(track_id) for track_id in args.liked_track_id),
        known_track_ids=tuple(str(track_id) for track_id in args.known_track_id),
        liked_artist_names=tuple(str(artist) for artist in args.liked_artist),
        blocked_artist_names=tuple(str(artist) for artist in args.blocked_artist),
    )
    service = AgenticRecommendationService(
        catalog=catalog,
        profile=profile,
        intent_parser=_live_intent_parser(args) if args.use_openai_agent else None,
    )
    response = service.recommend(
        prompt=str(args.prompt),
        limit=int(args.limit),
        create_playlist=bool(args.create_playlist),
    )
    print(json.dumps(response.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _data_root_value(data_root: str, data_mode: str | None) -> Path | str:
    if data_mode == "s3" or data_root.startswith("s3://"):
        return data_root
    return Path(data_root)


def _live_intent_parser(args: argparse.Namespace) -> Callable[[str], ParsedMoodIntent]:
    return lambda prompt: parse_intent_with_agent(prompt, model=args.openai_model)


if __name__ == "__main__":
    sys.exit(main())
