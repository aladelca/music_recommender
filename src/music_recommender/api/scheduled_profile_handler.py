from __future__ import annotations

import logging
from typing import Any, Protocol

from music_recommender.api.models import ProfileSyncRequest
from music_recommender.config import load_settings
from music_recommender.models import JsonDict
from music_recommender.recommender.profile import SpotifyProfileSyncService
from music_recommender.sources.spotify_user import SpotifyUserClient
from music_recommender.storage.dynamodb import DynamoDBProfileCache

LOGGER = logging.getLogger(__name__)

_PROFILE_COUNT_FIELDS = (
    "saved_tracks",
    "top_tracks",
    "top_artists",
    "playlists",
    "playlist_tracks",
    "recent_tracks",
)


class ScheduledProfileService(Protocol):
    def sync_profile(self, request: ProfileSyncRequest) -> JsonDict: ...


def handler(event: JsonDict, _context: Any) -> JsonDict:
    return run_scheduled_profile_sync(event, service=build_scheduled_profile_service())


class RuntimeScheduledProfileService:
    def __init__(
        self,
        *,
        sync_service: SpotifyProfileSyncService,
        spotify_client: SpotifyUserClient,
    ) -> None:
        self.sync_service = sync_service
        self.spotify_client = spotify_client

    def sync_profile(self, request: ProfileSyncRequest) -> JsonDict:
        try:
            return self.sync_service.sync_profile(
                top_limit=request.top_limit,
                saved_limit=request.saved_limit,
                top_time_ranges=tuple(request.top_time_ranges),
                include_playlists=request.include_playlists,
                playlist_limit=request.playlist_limit,
                playlist_track_limit=request.playlist_track_limit,
                playlist_ids=tuple(request.playlist_ids),
                include_recently_played=request.include_recently_played,
                recently_played_limit=request.recently_played_limit,
                market=request.market,
            ).to_dict()
        finally:
            self.spotify_client.close()


def build_scheduled_profile_service() -> RuntimeScheduledProfileService:
    settings = load_settings()
    if not settings.spotify_user_refresh_token:
        raise ValueError("SPOTIFY_USER_REFRESH_TOKEN is required for scheduled profile sync.")
    if not settings.users_table_name:
        raise ValueError("USERS_TABLE_NAME is required for scheduled profile sync.")

    spotify_client = SpotifyUserClient(
        client_id=settings.spotify_client_id,
        client_secret=settings.spotify_client_secret,
        refresh_token=settings.spotify_user_refresh_token,
    )
    cache = DynamoDBProfileCache(
        table_name=settings.users_table_name,
        user_id=settings.spotify_demo_user_id,
    )
    return RuntimeScheduledProfileService(
        sync_service=SpotifyProfileSyncService(
            spotify_client=spotify_client,
            cache=cache,
            required_user_id=settings.spotify_demo_user_id,
        ),
        spotify_client=spotify_client,
    )


def run_scheduled_profile_sync(
    event: JsonDict,
    *,
    service: ScheduledProfileService,
) -> JsonDict:
    if event.get("source") != "aws.events" or event.get("detail-type") != "Scheduled Event":
        raise ValueError("Expected an EventBridge scheduled event.")

    result = service.sync_profile(
        ProfileSyncRequest(
            top_limit=20,
            saved_limit=20,
            top_time_ranges=["short_term", "medium_term", "long_term"],
            include_playlists=True,
            playlist_limit=10,
            playlist_track_limit=50,
            include_recently_played=True,
            recently_played_limit=20,
        )
    )
    source_counts = _redacted_source_counts(result.get("source_counts"))
    missing_optional_scopes = _string_list(result.get("missing_optional_scopes"))
    LOGGER.info(
        "Scheduled Spotify profile sync completed with source counts: %s",
        source_counts,
    )
    return {
        "status": "ok",
        "synced_at": str(result.get("synced_at") or ""),
        "source_counts": source_counts,
        "missing_optional_scopes": missing_optional_scopes,
    }


def _redacted_source_counts(value: Any) -> JsonDict:
    if not isinstance(value, dict):
        return {field: 0 for field in _PROFILE_COUNT_FIELDS}
    return {field: _non_negative_int(value.get(field)) for field in _PROFILE_COUNT_FIELDS}


def _non_negative_int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return max(value, 0)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]
