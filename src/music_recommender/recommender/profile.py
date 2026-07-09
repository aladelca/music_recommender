from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from music_recommender.models import JsonDict
from music_recommender.recommender.models import UserTasteProfile
from music_recommender.recommender.profile_normalization import (
    apply_profile_track_signal,
    empty_profile_source_counts,
    normalize_spotify_track,
    optional_int,
    optional_str,
    playlist_owner_id,
    profile_top_weight,
    selected_profile_playlists,
    spotify_artist_names,
    spotify_items,
    spotify_url,
)
from music_recommender.sources.http import ApiError
from music_recommender.sources.spotify_user import TopItemType, TopTimeRange


class SpotifyProfileClient(Protocol):
    def get_current_user_profile(self) -> JsonDict: ...

    def iter_saved_tracks(
        self,
        *,
        limit_total: int,
        page_size: int = 50,
        market: str | None = None,
    ) -> Iterable[JsonDict]: ...

    def iter_top_items(
        self,
        item_type: TopItemType,
        *,
        limit_total: int,
        time_range: TopTimeRange = "medium_term",
        page_size: int = 50,
    ) -> Iterable[JsonDict]: ...

    def iter_current_user_playlists(
        self,
        *,
        limit_total: int,
        page_size: int = 50,
    ) -> Iterable[JsonDict]: ...

    def iter_playlist_items(
        self,
        playlist_id: str,
        *,
        limit_total: int,
        page_size: int = 50,
        market: str | None = None,
        fields: str | None = None,
    ) -> Iterable[JsonDict]: ...

    def get_recently_played(
        self,
        *,
        limit: int = 20,
        before: int | None = None,
        after: int | None = None,
    ) -> JsonDict: ...


@dataclass(frozen=True)
class ProfileSnapshot:
    profile: UserTasteProfile
    source: str
    synced_at: str
    spotify_account_id: str | None = None
    spotify_user_id: str | None = None
    source_counts: dict[str, int] = field(default_factory=dict)
    playlist_sources: tuple[JsonDict, ...] = ()
    time_ranges: tuple[str, ...] = ()
    missing_optional_scopes: tuple[str, ...] = ()
    spotify_track_candidates: tuple[JsonDict, ...] = ()

    def to_dict(self) -> JsonDict:
        return {
            "profile": _profile_to_dict(self.profile),
            "spotify_account_id": self.spotify_account_id,
            "spotify_user_id": self.spotify_user_id,
            "source": self.source,
            "source_counts": self.source_counts,
            "playlist_sources": list(self.playlist_sources),
            "synced_at": self.synced_at,
            "time_ranges": list(self.time_ranges),
            "missing_optional_scopes": list(self.missing_optional_scopes),
            "spotify_track_candidates": list(self.spotify_track_candidates),
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


class ProfileCache(Protocol):
    def load(self) -> ProfileSnapshot | None: ...

    def save(self, snapshot: ProfileSnapshot) -> None: ...


class SpotifyProfileSyncService:
    def __init__(
        self,
        *,
        spotify_client: SpotifyProfileClient,
        cache: ProfileCache,
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
        top_time_ranges: tuple[TopTimeRange, ...] = ("medium_term",),
        include_playlists: bool = True,
        playlist_limit: int = 10,
        playlist_track_limit: int = 50,
        playlist_ids: tuple[str, ...] = (),
        include_recently_played: bool = False,
        recently_played_limit: int = 20,
        market: str | None = None,
    ) -> ProfileSnapshot:
        current_user = self.spotify_client.get_current_user_profile()
        user_id = str(current_user["id"])
        if self.required_user_id and user_id != self.required_user_id:
            raise ValueError("Authenticated Spotify user does not match the configured demo user.")

        source_counts = _empty_source_counts()
        missing_optional_scopes: list[str] = []
        liked_track_ids: list[str] = []
        known_track_ids: list[str] = []
        liked_artist_names: list[str] = []
        artist_affinity: dict[str, float] = {}
        track_affinity: dict[str, float] = {}
        spotify_track_candidates: list[JsonDict] = []

        saved_tracks = [
            item["track"]
            for item in self.spotify_client.iter_saved_tracks(
                limit_total=saved_limit,
                market=market,
            )
            if isinstance(item.get("track"), dict)
        ]
        source_counts["saved_tracks"] = len(saved_tracks)
        for track in saved_tracks:
            _add_track_signal(
                track,
                liked_track_ids=liked_track_ids,
                known_track_ids=known_track_ids,
                liked_artist_names=liked_artist_names,
                track_affinity=track_affinity,
                artist_affinity=artist_affinity,
                track_weight=1.0,
                artist_weight=0.9,
                liked=True,
            )
            _append_track_candidate(spotify_track_candidates, track)

        for time_range in top_time_ranges:
            top_track_weight = _top_weight(time_range)
            top_tracks = list(
                self.spotify_client.iter_top_items(
                    "tracks",
                    limit_total=top_limit,
                    time_range=time_range,
                )
            )
            source_counts["top_tracks"] += len(top_tracks)
            for track in top_tracks:
                _add_track_signal(
                    track,
                    liked_track_ids=liked_track_ids,
                    known_track_ids=known_track_ids,
                    liked_artist_names=liked_artist_names,
                    track_affinity=track_affinity,
                    artist_affinity=artist_affinity,
                    track_weight=top_track_weight,
                    artist_weight=top_track_weight,
                    liked=True,
                )
                _append_track_candidate(spotify_track_candidates, track)

            top_artists = list(
                self.spotify_client.iter_top_items(
                    "artists",
                    limit_total=top_limit,
                    time_range=time_range,
                )
            )
            source_counts["top_artists"] += len(top_artists)
            for artist in top_artists:
                artist_name = _optional_str(artist.get("name"))
                if artist_name is None:
                    continue
                _append_unique(liked_artist_names, artist_name)
                _set_max(artist_affinity, artist_name, _top_weight(time_range))

        playlist_sources: list[JsonDict] = []
        if include_playlists and playlist_track_limit > 0:
            try:
                playlists = list(
                    self.spotify_client.iter_current_user_playlists(
                        limit_total=playlist_limit,
                    )
                )
            except ApiError as exc:
                if exc.status_code not in {401, 403}:
                    raise
                missing_optional_scopes.append("playlist-read-private")
            else:
                selected_playlists = _selected_playlists(playlists, playlist_ids)
                source_counts["playlists"] = len(selected_playlists)
                remaining_playlist_tracks = playlist_track_limit
                for playlist in selected_playlists:
                    playlist_id = _optional_str(playlist.get("id"))
                    if playlist_id is None:
                        continue
                    requested_track_count = min(remaining_playlist_tracks, playlist_track_limit)
                    if requested_track_count <= 0:
                        break
                    source_summary: JsonDict = {
                        "id": playlist_id,
                        "name": _optional_str(playlist.get("name")),
                        "owner_id": _playlist_owner_id(playlist),
                    }
                    try:
                        playlist_items = list(
                            self.spotify_client.iter_playlist_items(
                                playlist_id,
                                limit_total=requested_track_count,
                                market=market,
                                fields=(
                                    "items(added_at,track(id,name,artists(name))),"
                                    "total,next,limit,offset"
                                ),
                            )
                        )
                    except ApiError as exc:
                        if exc.status_code not in {401, 403}:
                            raise
                        playlist_sources.append(
                            {
                                **source_summary,
                                "tracks_read": 0,
                                "status": "skipped_inaccessible",
                            }
                        )
                        continue
                    playlist_tracks = [
                        item["track"]
                        for item in playlist_items
                        if isinstance(item.get("track"), dict)
                    ]
                    remaining_playlist_tracks -= len(playlist_tracks)
                    source_counts["playlist_tracks"] += len(playlist_tracks)
                    playlist_sources.append(
                        {
                            **source_summary,
                            "tracks_read": len(playlist_tracks),
                        }
                    )
                    weight = 0.6 if playlist_ids else 0.4
                    for track in playlist_tracks:
                        _add_track_signal(
                            track,
                            liked_track_ids=liked_track_ids,
                            known_track_ids=known_track_ids,
                            liked_artist_names=liked_artist_names,
                            track_affinity=track_affinity,
                            artist_affinity=artist_affinity,
                            track_weight=weight,
                            artist_weight=weight,
                            liked=False,
                        )
                        _append_track_candidate(spotify_track_candidates, track)

        if include_recently_played and recently_played_limit > 0:
            try:
                recent_tracks = [
                    item["track"]
                    for item in _items(
                        self.spotify_client.get_recently_played(limit=recently_played_limit)
                    )
                    if isinstance(item.get("track"), dict)
                ]
                source_counts["recent_tracks"] = len(recent_tracks)
                for track in recent_tracks:
                    _add_track_signal(
                        track,
                        liked_track_ids=liked_track_ids,
                        known_track_ids=known_track_ids,
                        liked_artist_names=liked_artist_names,
                        track_affinity=track_affinity,
                        artist_affinity=artist_affinity,
                        track_weight=0.3,
                        artist_weight=0.3,
                        liked=False,
                    )
                    _append_track_candidate(spotify_track_candidates, track)
            except ApiError as exc:
                if exc.status_code not in {401, 403}:
                    raise
                missing_optional_scopes.append("user-read-recently-played")

        profile = UserTasteProfile(
            user_id=user_id,
            liked_track_ids=tuple(liked_track_ids),
            known_track_ids=tuple(known_track_ids),
            liked_artist_names=tuple(liked_artist_names),
            artist_affinity=artist_affinity or None,
            track_affinity=track_affinity or None,
        )
        snapshot = ProfileSnapshot(
            profile=profile,
            spotify_account_id=_optional_str(current_user.get("account_id")),
            spotify_user_id=user_id,
            source="spotify",
            source_counts=source_counts,
            playlist_sources=tuple(playlist_sources),
            synced_at=datetime.now(UTC).isoformat(),
            time_ranges=tuple(top_time_ranges),
            missing_optional_scopes=tuple(missing_optional_scopes),
            spotify_track_candidates=tuple(spotify_track_candidates),
        )
        self.cache.save(snapshot)
        return snapshot

    def get_cached_profile(self) -> ProfileSnapshot | None:
        return self.cache.load()


def _profile_to_dict(profile: UserTasteProfile) -> JsonDict:
    payload: JsonDict = {
        "user_id": profile.user_id,
        "liked_track_ids": list(profile.liked_track_ids),
        "known_track_ids": list(profile.known_track_ids),
        "liked_artist_names": list(profile.liked_artist_names),
        "blocked_artist_names": list(profile.blocked_artist_names),
    }
    if profile.artist_affinity is not None:
        payload["artist_affinity"] = profile.artist_affinity
    if profile.track_affinity is not None:
        payload["track_affinity"] = profile.track_affinity
    return payload


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
            artist_affinity=_float_mapping_or_none(profile_payload.get("artist_affinity")),
            track_affinity=_float_mapping_or_none(profile_payload.get("track_affinity")),
        ),
        spotify_account_id=_optional_str(payload.get("spotify_account_id")),
        spotify_user_id=_optional_str(payload.get("spotify_user_id")),
        source=str(payload.get("source", "spotify")),
        source_counts=_int_mapping(payload.get("source_counts")),
        playlist_sources=tuple(
            dict(item) for item in payload.get("playlist_sources", []) if isinstance(item, dict)
        ),
        synced_at=str(payload["synced_at"]),
        time_ranges=tuple(str(item) for item in payload.get("time_ranges", [])),
        missing_optional_scopes=tuple(
            str(item) for item in payload.get("missing_optional_scopes", [])
        ),
        spotify_track_candidates=_track_candidates_from_payload(
            payload.get("spotify_track_candidates")
        ),
    )


def profile_snapshot_from_dict(payload: JsonDict) -> ProfileSnapshot:
    return _snapshot_from_payload(payload)


def _items(payload: JsonDict) -> list[JsonDict]:
    return spotify_items(payload)


def _append_track_candidate(candidates: list[JsonDict], track: JsonDict) -> None:
    candidate = _track_candidate_from_spotify_track(track)
    if candidate is None:
        return
    if any(existing.get("id") == candidate["id"] for existing in candidates):
        return
    candidates.append(candidate)


def _track_candidate_from_spotify_track(track: JsonDict) -> JsonDict | None:
    normalized = normalize_spotify_track(track)
    if normalized is None:
        return None
    return normalized.candidate()


def _track_candidates_from_payload(value: Any) -> tuple[JsonDict, ...]:
    if not isinstance(value, list):
        return ()
    candidates: list[JsonDict] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        candidate = _track_candidate_from_payload(item)
        if candidate is None:
            continue
        if any(existing.get("id") == candidate["id"] for existing in candidates):
            continue
        candidates.append(candidate)
    return tuple(candidates)


def _track_candidate_from_payload(payload: JsonDict) -> JsonDict | None:
    track_id = _optional_str(payload.get("id"))
    if track_id is None:
        return None
    artist_names = _string_list(payload.get("artist_names"))
    primary_artist_name = _optional_str(payload.get("primary_artist_name"))
    return {
        "id": track_id,
        "name": _optional_str(payload.get("name")) or track_id,
        "artist_names": artist_names,
        "primary_artist_name": primary_artist_name or (artist_names[0] if artist_names else None),
        "explicit": bool(payload.get("explicit") or False),
        "popularity": _optional_int(payload.get("popularity")),
        "spotify_url": _optional_str(payload.get("spotify_url")),
    }


def _spotify_url(track: JsonDict) -> str | None:
    return spotify_url(track)


def _track_ids(tracks: list[JsonDict]) -> list[str]:
    return [str(track["id"]) for track in tracks if track.get("id")]


def _artist_names(tracks: list[JsonDict]) -> list[str]:
    names: list[str] = []
    for track in tracks:
        names.extend(spotify_artist_names(track))
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


def _empty_source_counts() -> dict[str, int]:
    return empty_profile_source_counts()


def _add_track_signal(
    track: JsonDict,
    *,
    liked_track_ids: list[str],
    known_track_ids: list[str],
    liked_artist_names: list[str],
    track_affinity: dict[str, float],
    artist_affinity: dict[str, float],
    track_weight: float,
    artist_weight: float,
    liked: bool,
) -> None:
    apply_profile_track_signal(
        track,
        liked_track_ids=liked_track_ids,
        known_track_ids=known_track_ids,
        liked_artist_names=liked_artist_names,
        track_affinity=track_affinity,
        artist_affinity=artist_affinity,
        track_weight=track_weight,
        artist_weight=artist_weight,
        liked=liked,
    )


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def _set_max(values: dict[str, float], key: str, value: float) -> None:
    values[key] = max(values.get(key, 0.0), value)


def _top_weight(time_range: str) -> float:
    return profile_top_weight(time_range)


def _selected_playlists(
    playlists: list[JsonDict],
    playlist_ids: tuple[str, ...],
) -> list[JsonDict]:
    return selected_profile_playlists(playlists, playlist_ids)


def _playlist_owner_id(playlist: JsonDict) -> str | None:
    return playlist_owner_id(playlist)


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list | tuple):
        return [str(item) for item in value if item is not None]
    return [str(value)]


def _optional_str(value: Any) -> str | None:
    return optional_str(value)


def _float_mapping_or_none(value: Any) -> dict[str, float] | None:
    if not isinstance(value, dict):
        return None
    mapping = {
        str(key): float(raw_value) for key, raw_value in value.items() if raw_value is not None
    }
    return mapping or None


def _int_mapping(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    return {str(key): int(raw_value) for key, raw_value in value.items() if raw_value is not None}


def _optional_int(value: Any) -> int | None:
    return optional_int(value)
