from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

JsonDict = dict[str, Any]


@dataclass(frozen=True)
class SeedArtist:
    original: str
    name: str

    def to_dict(self) -> JsonDict:
        return asdict(self)


@dataclass(frozen=True)
class SpotifyArtist:
    id: str
    name: str
    popularity: int | None
    genres: list[str]
    spotify_url: str | None
    seed_artist: str
    raw: JsonDict

    @classmethod
    def from_raw(cls, raw: JsonDict, seed_artist: str) -> SpotifyArtist:
        external_urls = raw.get("external_urls") or {}
        return cls(
            id=str(raw["id"]),
            name=str(raw["name"]),
            popularity=raw.get("popularity"),
            genres=[str(genre) for genre in raw.get("genres", [])],
            spotify_url=external_urls.get("spotify"),
            seed_artist=seed_artist,
            raw=raw,
        )

    def bronze_record(self, run_id: str, fetched_at: str) -> JsonDict:
        return {
            "run_id": run_id,
            "source": "spotify",
            "seed_artist": self.seed_artist,
            "spotify_artist_id": self.id,
            "raw": self.raw,
            "fetched_at": fetched_at,
        }

    def silver_record(self, run_id: str) -> JsonDict:
        return {
            "spotify_artist_id": self.id,
            "artist_name": self.name,
            "seed_artist": self.seed_artist,
            "popularity": self.popularity,
            "genres": self.genres,
            "spotify_url": self.spotify_url,
            "source_run_id": run_id,
        }


@dataclass(frozen=True)
class SpotifyAlbum:
    id: str
    name: str
    album_type: str | None
    release_date: str | None
    total_tracks: int | None
    artist_id: str
    seed_artist: str
    raw: JsonDict

    @classmethod
    def from_raw(cls, raw: JsonDict, artist_id: str, seed_artist: str) -> SpotifyAlbum:
        return cls(
            id=str(raw["id"]),
            name=str(raw["name"]),
            album_type=raw.get("album_type"),
            release_date=raw.get("release_date"),
            total_tracks=raw.get("total_tracks"),
            artist_id=artist_id,
            seed_artist=seed_artist,
            raw=raw,
        )

    def bronze_record(self, run_id: str, fetched_at: str) -> JsonDict:
        return {
            "run_id": run_id,
            "source": "spotify",
            "seed_artist": self.seed_artist,
            "spotify_artist_id": self.artist_id,
            "spotify_album_id": self.id,
            "raw": self.raw,
            "fetched_at": fetched_at,
        }

    def silver_record(self, run_id: str) -> JsonDict:
        return {
            "spotify_album_id": self.id,
            "spotify_artist_id": self.artist_id,
            "album_name": self.name,
            "album_type": self.album_type,
            "release_date": self.release_date,
            "total_tracks": self.total_tracks,
            "seed_artist": self.seed_artist,
            "source_run_id": run_id,
        }


@dataclass(frozen=True)
class SpotifyTrack:
    id: str
    name: str
    duration_ms: int | None
    explicit: bool | None
    popularity: int | None
    isrc: str | None
    album_id: str | None
    album_name: str | None
    album_release_date: str | None
    artist_names: list[str]
    primary_artist_name: str | None
    spotify_url: str | None
    seed_artist: str
    spotify_artist_id: str
    raw: JsonDict

    @classmethod
    def from_raw(
        cls,
        raw: JsonDict,
        *,
        seed_artist: str,
        spotify_artist_id: str,
    ) -> SpotifyTrack:
        artists = raw.get("artists") or []
        artist_names = [str(artist["name"]) for artist in artists if artist.get("name")]
        album = raw.get("album") or {}
        external_ids = raw.get("external_ids") or {}
        external_urls = raw.get("external_urls") or {}
        return cls(
            id=str(raw["id"]),
            name=str(raw["name"]),
            duration_ms=raw.get("duration_ms"),
            explicit=raw.get("explicit"),
            popularity=raw.get("popularity"),
            isrc=external_ids.get("isrc"),
            album_id=album.get("id"),
            album_name=album.get("name"),
            album_release_date=album.get("release_date"),
            artist_names=artist_names,
            primary_artist_name=artist_names[0] if artist_names else None,
            spotify_url=external_urls.get("spotify"),
            seed_artist=seed_artist,
            spotify_artist_id=spotify_artist_id,
            raw=raw,
        )

    def bronze_record(self, run_id: str, fetched_at: str) -> JsonDict:
        return {
            "run_id": run_id,
            "source": "spotify",
            "seed_artist": self.seed_artist,
            "spotify_artist_id": self.spotify_artist_id,
            "spotify_track_id": self.id,
            "raw": self.raw,
            "fetched_at": fetched_at,
        }

    def silver_record(self, run_id: str) -> JsonDict:
        return {
            "spotify_track_id": self.id,
            "isrc": self.isrc,
            "track_name": self.name,
            "artist_names": self.artist_names,
            "primary_artist_name": self.primary_artist_name,
            "album_id": self.album_id,
            "album_name": self.album_name,
            "release_date": self.album_release_date,
            "duration_ms": self.duration_ms,
            "explicit": self.explicit,
            "popularity": self.popularity,
            "spotify_url": self.spotify_url,
            "seed_artist": self.seed_artist,
            "source_run_id": run_id,
        }


@dataclass(frozen=True)
class AudioFeaturesRecord:
    spotify_track_id: str
    enabled: bool
    status: str
    source: str = "spotify"
    isrc: str | None = None
    raw: JsonDict | None = None
    error_code: int | None = None
    fetched_at: str | None = None

    def to_dict(self) -> JsonDict:
        return asdict(self)

    def silver_record(self, run_id: str) -> JsonDict:
        raw = self.raw or {}
        return {
            "spotify_track_id": self.spotify_track_id,
            "isrc": self.isrc or _optional_str(raw.get("isrc")),
            "acousticness": _optional_float(raw.get("acousticness")),
            "danceability": _optional_float(raw.get("danceability")),
            "energy": _optional_float(raw.get("energy")),
            "instrumentalness": _optional_float(raw.get("instrumentalness")),
            "key": _optional_int(raw.get("key")),
            "liveness": _optional_float(raw.get("liveness")),
            "loudness": _optional_float(raw.get("loudness")),
            "mode": _optional_int(raw.get("mode")),
            "speechiness": _optional_float(raw.get("speechiness")),
            "tempo": _optional_float(raw.get("tempo")),
            "valence": _optional_float(raw.get("valence")),
            "audio_feature_source": self.source,
            "source_run_id": run_id,
        }


@dataclass(frozen=True)
class LyricsRecord:
    spotify_track_id: str
    track_name: str
    artist_name: str
    album_name: str | None
    duration_ms: int | None
    lyrics_source: str
    match_status: str
    plain_lyrics: str | None = None
    synced_lyrics: str | None = None
    lrclib_id: int | None = None
    fetched_at: str | None = None
    raw: JsonDict | None = None

    def to_dict(self) -> JsonDict:
        return asdict(self)

    def silver_record(self, run_id: str) -> JsonDict:
        return {
            "spotify_track_id": self.spotify_track_id,
            "track_name": self.track_name,
            "artist_name": self.artist_name,
            "album_name": self.album_name,
            "duration_ms": self.duration_ms,
            "lyrics_source": self.lyrics_source,
            "match_status": self.match_status,
            "plain_lyrics": self.plain_lyrics,
            "synced_lyrics": self.synced_lyrics,
            "lrclib_id": self.lrclib_id,
            "source_run_id": run_id,
        }


@dataclass(frozen=True)
class LyricsNlpRecord:
    spotify_track_id: str
    lyrics_source: str
    language: str
    language_confidence: float | None
    language_model: str
    sentiment_label: str
    sentiment_score: float | None
    negative_score: float | None
    neutral_score: float | None
    positive_score: float | None
    sentiment_model: str
    chunk_count: int
    source_run_id: str

    def to_dict(self) -> JsonDict:
        return asdict(self)


@dataclass(frozen=True)
class ListenBrainzListenRecord:
    user_id_hash: str
    listened_at: int | None
    recording_mbid: str | None
    artist_name: str | None
    track_name: str | None
    release_name: str | None
    isrc: str | None
    spotify_track_id: str | None
    source: str
    source_run_id: str

    def to_dict(self) -> JsonDict:
        return asdict(self)


@dataclass(frozen=True)
class UserTrackInteractionRecord:
    user_id_hash: str
    item_id: str
    item_id_type: str
    listen_count: int
    first_listened_at: int | None
    last_listened_at: int | None
    implicit_rating: float
    source_run_id: str

    def to_dict(self) -> JsonDict:
        return asdict(self)


@dataclass(frozen=True)
class LinkedListenRecord:
    user_id_hash: str
    listened_at: int | None
    spotify_track_id: str | None
    item_id_type: str | None
    artist_name: str | None
    track_name: str | None
    catalog_spotify_track_id: str
    catalog_track_name: str | None
    catalog_primary_artist_name: str | None
    catalog_match_method: str
    source: str
    source_run_id: str

    def to_dict(self) -> JsonDict:
        return asdict(self)


@dataclass
class ExtractionSummary:
    run_id: str
    outputs: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> JsonDict:
        return asdict(self)


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
