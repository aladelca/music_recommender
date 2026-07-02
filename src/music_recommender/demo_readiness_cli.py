from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
from pathlib import Path

from dotenv import load_dotenv

from music_recommender.config import Settings, load_settings
from music_recommender.recommender.data import check_local_recommender_data
from music_recommender.sources.spotify_user import (
    SpotifyUserClient,
    build_authorization_url,
    missing_required_scopes,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run beta demo readiness checks.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    check_data = subparsers.add_parser("check-data", help="Read local recommender Parquet outputs.")
    check_data.add_argument("--data-root", type=Path, default=None)
    check_data.add_argument("--run-id", default=None)

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
    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv(".env")
    parser = build_parser()
    args = parser.parse_args(argv)
    command = str(args.command)
    if command == "check-data":
        return _check_data(args)
    if command == "auth-url":
        return _auth_url(args)
    if command == "exchange-code":
        return _exchange_code(args)
    if command == "refresh-spotify-token":
        return _refresh_spotify_token()
    parser.error(f"Unknown command: {command}")


def _check_data(args: argparse.Namespace) -> int:
    data_root = args.data_root or Path(os.getenv("RECOMMENDER_DATA_ROOT", "data/local"))
    summary = check_local_recommender_data(data_root, run_id=args.run_id)
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


def _build_user_client(settings: Settings) -> SpotifyUserClient:
    return SpotifyUserClient(
        client_id=settings.spotify_client_id,
        client_secret=settings.spotify_client_secret,
        refresh_token=settings.spotify_user_refresh_token,
    )


if __name__ == "__main__":
    sys.exit(main())
