from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from music_recommender.models import JsonDict


@dataclass(frozen=True)
class NormalizedSpotifyArtist:
    spotify_artist_id: str | None
    artist_name: str


@dataclass(frozen=True)
class NormalizedSpotifyTrack:
    spotify_track_id: str
    track_name: str
    artists: tuple[NormalizedSpotifyArtist, ...]
    artist_names: tuple[str, ...]
    primary_artist_name: str | None
    spotify_url: str | None
    popularity: int | None
    explicit: bool | None
    duration_ms: int | None
    isrc: str | None

    def candidate(self) -> JsonDict:
        return {
            "id": self.spotify_track_id,
            "name": self.track_name,
            "artist_names": list(self.artist_names),
            "primary_artist_name": self.primary_artist_name,
            "explicit": bool(self.explicit or False),
            "popularity": self.popularity,
            "spotify_url": self.spotify_url,
        }


def apply_profile_track_signal(
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
) -> NormalizedSpotifyTrack | None:
    normalized = normalize_spotify_track(track)
    if normalized is None:
        return None
    _append_unique(known_track_ids, normalized.spotify_track_id)
    _set_max(track_affinity, normalized.spotify_track_id, track_weight)
    if liked:
        _append_unique(liked_track_ids, normalized.spotify_track_id)
    for artist_name in normalized.artist_names:
        if liked:
            _append_unique(liked_artist_names, artist_name)
        _set_max(artist_affinity, artist_name, artist_weight)
    return normalized


def normalize_spotify_track(track: JsonDict) -> NormalizedSpotifyTrack | None:
    track_id = optional_str(track.get("id"))
    if track_id is None:
        return None
    artists = tuple(
        NormalizedSpotifyArtist(
            spotify_artist_id=optional_str(artist.get("id")),
            artist_name=artist_name,
        )
        for artist in spotify_artists(track)
        if (artist_name := optional_str(artist.get("name"))) is not None
    )
    artist_names = tuple(artist.artist_name for artist in artists)
    return NormalizedSpotifyTrack(
        spotify_track_id=track_id,
        track_name=optional_str(track.get("name")) or track_id,
        artists=artists,
        artist_names=artist_names,
        primary_artist_name=artist_names[0] if artist_names else None,
        spotify_url=spotify_url(track),
        popularity=optional_int(track.get("popularity")),
        explicit=optional_bool(track.get("explicit")),
        duration_ms=optional_int(track.get("duration_ms")),
        isrc=track_isrc(track),
    )


def empty_profile_source_counts() -> dict[str, int]:
    return {
        "saved_tracks": 0,
        "top_tracks": 0,
        "top_artists": 0,
        "playlists": 0,
        "playlist_tracks": 0,
        "recent_tracks": 0,
    }


def profile_top_weight(time_range: str) -> float:
    return {
        "short_term": 0.9,
        "medium_term": 0.8,
        "long_term": 0.7,
    }.get(time_range, 0.8)


def spotify_items(payload: JsonDict) -> list[JsonDict]:
    items = payload.get("items", [])
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def selected_profile_playlists(
    playlists: list[JsonDict],
    playlist_ids: tuple[str, ...],
) -> list[JsonDict]:
    if not playlist_ids:
        return playlists
    by_id = {
        str(playlist["id"]): playlist
        for playlist in playlists
        if optional_str(playlist.get("id")) is not None
    }
    return [
        by_id.get(playlist_id, {"id": playlist_id, "name": None, "owner": {}})
        for playlist_id in playlist_ids
    ]


def playlist_owner_id(playlist: JsonDict) -> str | None:
    owner = playlist.get("owner")
    if not isinstance(owner, dict):
        return None
    return optional_str(owner.get("id"))


def spotify_artists(track: JsonDict) -> list[JsonDict]:
    artists = track.get("artists", [])
    if not isinstance(artists, list):
        return []
    return [artist for artist in artists if isinstance(artist, dict)]


def spotify_artist_names(track: JsonDict) -> list[str]:
    return [artist.artist_name for artist in normalize_spotify_artists(track)]


def normalize_spotify_artists(track: JsonDict) -> tuple[NormalizedSpotifyArtist, ...]:
    return tuple(
        NormalizedSpotifyArtist(
            spotify_artist_id=optional_str(artist.get("id")),
            artist_name=artist_name,
        )
        for artist in spotify_artists(track)
        if (artist_name := optional_str(artist.get("name"))) is not None
    )


def spotify_url(track: JsonDict) -> str | None:
    external_urls = track.get("external_urls")
    if not isinstance(external_urls, dict):
        return None
    return optional_str(external_urls.get("spotify"))


def track_isrc(track: JsonDict) -> str | None:
    external_ids = track.get("external_ids")
    if not isinstance(external_ids, dict):
        return None
    return optional_str(external_ids.get("isrc"))


def optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        if isinstance(value, int | float | str | bytes | bytearray):
            return int(value)
    except (TypeError, ValueError):
        return None
    return None


def optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    return bool(value)


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def _set_max(values: dict[str, float], key: str, value: float) -> None:
    values[key] = max(values.get(key, 0.0), value)
