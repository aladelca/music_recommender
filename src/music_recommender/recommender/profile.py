from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from music_recommender.models import JsonDict
from music_recommender.recommender.models import UserTasteProfile
from music_recommender.sources.spotify_user import TopItemType, TopTimeRange


class SpotifyProfileClient(Protocol):
    def get_current_user_profile(self) -> JsonDict: ...

    def get_top_items(
        self,
        item_type: TopItemType,
        *,
        limit: int = 20,
        offset: int = 0,
        time_range: TopTimeRange = "medium_term",
    ) -> JsonDict: ...

    def get_saved_tracks(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        market: str | None = None,
    ) -> JsonDict: ...


@dataclass(frozen=True)
class ProfileSnapshot:
    profile: UserTasteProfile
    source: str
    synced_at: str

    def to_dict(self) -> JsonDict:
        return {
            "profile": _profile_to_dict(self.profile),
            "source": self.source,
            "synced_at": self.synced_at,
        }


class JsonProfileCache:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> ProfileSnapshot | None:
        if not self.path.exists():
            return None
        payload = json.loads(self.path.read_text())
        if not isinstance(payload, dict):
            raise ValueError(f"Profile cache must contain a JSON object: {self.path}")
        return _snapshot_from_payload(payload)

    def save(self, snapshot: ProfileSnapshot) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(snapshot.to_dict(), indent=2, sort_keys=True))


class SpotifyProfileSyncService:
    def __init__(
        self,
        *,
        spotify_client: SpotifyProfileClient,
        cache: JsonProfileCache,
        required_user_id: str | None = None,
    ) -> None:
        self.spotify_client = spotify_client
        self.cache = cache
        self.required_user_id = required_user_id

    def sync_profile(
        self,
        *,
        top_limit: int = 20,
        saved_limit: int = 20,
        market: str | None = None,
    ) -> ProfileSnapshot:
        current_user = self.spotify_client.get_current_user_profile()
        user_id = str(current_user["id"])
        if self.required_user_id and user_id != self.required_user_id:
            raise ValueError("Authenticated Spotify user does not match the configured demo user.")

        top_tracks = _items(self.spotify_client.get_top_items("tracks", limit=top_limit))
        top_artists = _items(self.spotify_client.get_top_items("artists", limit=top_limit))
        saved_tracks = [
            item["track"]
            for item in _items(
                self.spotify_client.get_saved_tracks(limit=saved_limit, market=market)
            )
            if isinstance(item.get("track"), dict)
        ]
        liked_track_ids = _unique([*_track_ids(top_tracks), *_track_ids(saved_tracks)])
        liked_artist_names = _unique(
            [
                *_artist_names(top_tracks),
                *_artist_names(saved_tracks),
                *_top_artist_names(top_artists),
            ]
        )
        profile = UserTasteProfile(
            user_id=user_id,
            liked_track_ids=liked_track_ids,
            known_track_ids=liked_track_ids,
            liked_artist_names=liked_artist_names,
        )
        snapshot = ProfileSnapshot(
            profile=profile,
            source="spotify",
            synced_at=datetime.now(UTC).isoformat(),
        )
        self.cache.save(snapshot)
        return snapshot

    def get_cached_profile(self) -> ProfileSnapshot | None:
        return self.cache.load()


def _profile_to_dict(profile: UserTasteProfile) -> JsonDict:
    return {
        "user_id": profile.user_id,
        "liked_track_ids": list(profile.liked_track_ids),
        "known_track_ids": list(profile.known_track_ids),
        "liked_artist_names": list(profile.liked_artist_names),
        "blocked_artist_names": list(profile.blocked_artist_names),
    }


def _snapshot_from_payload(payload: JsonDict) -> ProfileSnapshot:
    profile_payload = payload.get("profile")
    if not isinstance(profile_payload, dict):
        raise ValueError("Profile cache is missing profile object.")
    return ProfileSnapshot(
        profile=UserTasteProfile(
            user_id=str(profile_payload["user_id"]),
            liked_track_ids=tuple(str(item) for item in profile_payload.get("liked_track_ids", [])),
            known_track_ids=tuple(str(item) for item in profile_payload.get("known_track_ids", [])),
            liked_artist_names=tuple(
                str(item) for item in profile_payload.get("liked_artist_names", [])
            ),
            blocked_artist_names=tuple(
                str(item) for item in profile_payload.get("blocked_artist_names", [])
            ),
        ),
        source=str(payload.get("source", "spotify")),
        synced_at=str(payload["synced_at"]),
    )


def _items(payload: JsonDict) -> list[JsonDict]:
    items = payload.get("items", [])
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def _track_ids(tracks: list[JsonDict]) -> list[str]:
    return [str(track["id"]) for track in tracks if track.get("id")]


def _artist_names(tracks: list[JsonDict]) -> list[str]:
    names: list[str] = []
    for track in tracks:
        artists = track.get("artists", [])
        if not isinstance(artists, list):
            continue
        names.extend(
            str(artist["name"])
            for artist in artists
            if isinstance(artist, dict) and artist.get("name")
        )
    return names


def _top_artist_names(artists: list[JsonDict]) -> list[str]:
    return [str(artist["name"]) for artist in artists if artist.get("name")]


def _unique(values: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    unique_values: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        unique_values.append(value)
    return tuple(unique_values)
