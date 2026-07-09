from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
from pathlib import Path
from typing import Any, Protocol

from dotenv import load_dotenv

from music_recommender.config import Settings, load_settings
from music_recommender.models import JsonDict
from music_recommender.recommender.data import (
    check_local_recommender_data,
    check_s3_recommender_data,
)
from music_recommender.sources.spotify_user import (
    SpotifyUserClient,
    TopItemType,
    TopTimeRange,
    build_authorization_url,
    missing_required_scopes,
)


class LiveProfileCheckClient(Protocol):
    def refresh_access_token(self, *, required_scopes: tuple[str, ...] = ()) -> Any: ...

    def get_current_user_profile(self) -> JsonDict: ...

    def get_saved_tracks(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        market: str | None = None,
    ) -> JsonDict: ...

    def get_top_items(
        self,
        item_type: TopItemType,
        *,
        limit: int = 20,
        offset: int = 0,
        time_range: TopTimeRange = "medium_term",
    ) -> JsonDict: ...

    def get_current_user_playlists(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
    ) -> JsonDict: ...

    def get_recently_played(
        self,
        *,
        limit: int = 20,
        before: int | None = None,
        after: int | None = None,
    ) -> JsonDict: ...


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run beta demo readiness checks.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    check_data = subparsers.add_parser("check-data", help="Read local recommender Parquet outputs.")
    check_data.add_argument("--data-root", type=Path, default=None)
    check_data.add_argument("--run-id", default=None)

    check_s3_data = subparsers.add_parser(
        "check-s3-data",
        help="Read S3 recommender Parquet outputs for a run.",
    )
    check_s3_data.add_argument("--data-root", default=None)
    check_s3_data.add_argument("--bucket", default=None)
    check_s3_data.add_argument("--run-id", "--catalog-run-id", dest="run_id", required=True)

    auth_url = subparsers.add_parser("auth-url", help="Print the Spotify OAuth URL.")
    auth_url.add_argument("--state", default=None)

    exchange_code = subparsers.add_parser(
        "exchange-code",
        help="Exchange a Spotify OAuth code for tokens.",
    )
    exchange_code.add_argument("--code", required=True)
    exchange_code.add_argument(
        "--show-refresh-token",
        action="store_true",
        help="Print the refresh token so it can be copied into .env.",
    )

    subparsers.add_parser(
        "refresh-spotify-token",
        help="Refresh the Spotify user token and validate configured scopes.",
    )

    check_live_profile = subparsers.add_parser(
        "check-live-profile",
        help="Validate Spotify profile scopes and fetch redacted live profile sample counts.",
    )
    check_live_profile.add_argument("--include-playlists", action="store_true")
    check_live_profile.add_argument("--include-recently-played", action="store_true")
    check_live_profile.add_argument("--sample-limit", type=int, default=5)
    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv(".env")
    parser = build_parser()
    args = parser.parse_args(argv)
    command = str(args.command)
    if command == "check-data":
        return _check_data(args)
    if command == "check-s3-data":
        return _check_s3_data(args)
    if command == "auth-url":
        return _auth_url(args)
    if command == "exchange-code":
        return _exchange_code(args)
    if command == "refresh-spotify-token":
        return _refresh_spotify_token()
    if command == "check-live-profile":
        return _check_live_profile(args)
    parser.error(f"Unknown command: {command}")


def _check_data(args: argparse.Namespace) -> int:
    data_root = args.data_root or Path(os.getenv("RECOMMENDER_DATA_ROOT", "data/local"))
    summary = check_local_recommender_data(data_root, run_id=args.run_id)
    print(json.dumps(summary.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _check_s3_data(args: argparse.Namespace) -> int:
    bucket = args.bucket or os.getenv("MUSIC_RECOMMENDER_BUCKET")
    data_root = args.data_root or (f"s3://{bucket}" if bucket else None)
    if data_root is None:
        raise SystemExit("--data-root, --bucket, or MUSIC_RECOMMENDER_BUCKET is required")
    summary = check_s3_recommender_data(str(data_root), run_id=str(args.run_id))
    print(json.dumps(summary.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _auth_url(args: argparse.Namespace) -> int:
    settings = load_settings()
    state = args.state or secrets.token_urlsafe(16)
    payload = {
        "authorization_url": build_authorization_url(
            client_id=settings.spotify_client_id,
            redirect_uri=settings.spotify_redirect_uri,
            scopes=settings.spotify_user_scopes,
            state=state,
        ),
        "redirect_uri": settings.spotify_redirect_uri,
        "scopes": list(settings.spotify_user_scopes),
        "state": state,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _exchange_code(args: argparse.Namespace) -> int:
    settings = load_settings()
    client = _build_user_client(settings)
    try:
        token = client.exchange_authorization_code(
            code=args.code,
            redirect_uri=settings.spotify_redirect_uri,
            required_scopes=settings.spotify_user_scopes,
        )
    finally:
        client.close()
    missing_scopes = missing_required_scopes(token.scope, settings.spotify_user_scopes)
    payload: dict[str, object] = {
        "access_token_present": bool(token.access_token),
        "expires_in": token.expires_in,
        "missing_required_scopes": missing_scopes,
        "refresh_token": token.refresh_token if args.show_refresh_token else "<redacted>",
        "refresh_token_present": token.refresh_token is not None,
        "scope": token.scope,
        "token_type": token.token_type,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _refresh_spotify_token() -> int:
    settings = load_settings()
    client = _build_user_client(settings)
    try:
        token = client.refresh_access_token(required_scopes=settings.spotify_user_scopes)
    finally:
        client.close()
    payload = {
        "access_token_present": bool(token.access_token),
        "expires_in": token.expires_in,
        "missing_required_scopes": missing_required_scopes(
            token.scope,
            settings.spotify_user_scopes,
        ),
        "scope": token.scope,
        "token_type": token.token_type,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _check_live_profile(args: argparse.Namespace) -> int:
    settings = load_settings()
    client = _build_user_client(settings)
    try:
        payload = _live_profile_check_payload(
            settings,
            client=client,
            include_playlists=bool(args.include_playlists),
            include_recently_played=bool(args.include_recently_played),
            sample_limit=int(args.sample_limit),
        )
    finally:
        client.close()
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _live_profile_check_payload(
    settings: Settings,
    *,
    client: LiveProfileCheckClient,
    include_playlists: bool,
    include_recently_played: bool,
    sample_limit: int,
) -> JsonDict:
    bounded_sample_limit = max(1, min(sample_limit, 50))
    required_scopes = _profile_required_scopes(
        settings,
        include_playlists=include_playlists,
        include_recently_played=include_recently_played,
    )
    client.refresh_access_token(required_scopes=required_scopes)
    current_user = client.get_current_user_profile()
    payload: JsonDict = {
        "account_id_present": bool(current_user.get("account_id")),
        "missing_required_scopes": [],
        "saved_track_sample_count": _item_count(
            client.get_saved_tracks(limit=bounded_sample_limit, market=settings.spotify_market)
        ),
        "top_artist_sample_count": _item_count(
            client.get_top_items("artists", limit=bounded_sample_limit)
        ),
        "top_track_sample_count": _item_count(
            client.get_top_items("tracks", limit=bounded_sample_limit)
        ),
        "user_id": str(current_user.get("id", "")),
    }
    if include_playlists:
        payload["playlist_sample_count"] = _item_count(
            client.get_current_user_playlists(limit=bounded_sample_limit)
        )
    if include_recently_played:
        payload["recent_track_sample_count"] = _item_count(
            client.get_recently_played(limit=bounded_sample_limit)
        )
    return payload


def _profile_required_scopes(
    _settings: Settings,
    *,
    include_playlists: bool,
    include_recently_played: bool,
) -> tuple[str, ...]:
    scopes = {"user-library-read", "user-top-read"}
    if include_playlists:
        scopes.add("playlist-read-private")
    if include_recently_played:
        scopes.add("user-read-recently-played")
    return tuple(sorted(scopes))


def _item_count(payload: JsonDict) -> int:
    items = payload.get("items", [])
    return len(items) if isinstance(items, list) else 0


def _build_user_client(settings: Settings) -> SpotifyUserClient:
    return SpotifyUserClient(
        client_id=settings.spotify_client_id,
        client_secret=settings.spotify_client_secret,
        refresh_token=settings.spotify_user_refresh_token,
    )


if __name__ == "__main__":
    sys.exit(main())
