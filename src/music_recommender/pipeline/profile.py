from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from music_recommender.models import (
    ExtractionSummary,
    JsonDict,
    SpotifyProfileArtistSignalRecord,
    SpotifyProfileTrackSignalRecord,
    UserTrackInteractionRecord,
)
from music_recommender.sources.http import ApiError
from music_recommender.sources.spotify_user import TopItemType, TopTimeRange
from music_recommender.storage.s3 import FileFormat, S3Storage, medallion_data_key, run_metadata_key

LOGGER = logging.getLogger(__name__)


class SpotifyProfileSource(Protocol):
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
class SpotifyProfileExtractionOptions:
    run_id: str
    run_date: str
    file_format: FileFormat
    top_limit: int = 20
    saved_limit: int = 20
    top_time_ranges: tuple[TopTimeRange, ...] = ("medium_term",)
    include_playlists: bool = True
    playlist_limit: int = 10
    playlist_track_limit: int = 50
    playlist_ids: tuple[str, ...] = ()
    include_recently_played: bool = False
    recently_played_limit: int = 20
    market: str | None = None
    required_user_id: str | None = None


class SpotifyProfileExtractor:
    def __init__(
        self,
        *,
        spotify_client: SpotifyProfileSource,
        storage: S3Storage,
    ) -> None:
        self.spotify_client = spotify_client
        self.storage = storage

    def run(self, options: SpotifyProfileExtractionOptions) -> ExtractionSummary:
        summary = ExtractionSummary(run_id=options.run_id)
        current_user = self.spotify_client.get_current_user_profile()
        spotify_user_id = str(current_user["id"])
        if options.required_user_id and spotify_user_id != options.required_user_id:
            raise ValueError("Authenticated Spotify user does not match the configured demo user.")
        spotify_account_id = _optional_str(current_user.get("account_id"))

        track_signals = _TrackSignalAccumulator()
        artist_signals = _ArtistSignalAccumulator()
        source_counts = _empty_source_counts()
        bronze_saved_tracks: list[JsonDict] = []
        bronze_top_tracks: list[JsonDict] = []
        bronze_top_artists: list[JsonDict] = []
        bronze_playlists: list[JsonDict] = []
        bronze_playlist_tracks: list[JsonDict] = []
        bronze_recent_tracks: list[JsonDict] = []

        saved_tracks = [
            item["track"]
            for item in self.spotify_client.iter_saved_tracks(
                limit_total=options.saved_limit,
                market=options.market,
            )
            if isinstance(item.get("track"), dict)
        ]
        source_counts["saved_tracks"] = len(saved_tracks)
        for track in saved_tracks:
            bronze_saved_tracks.append(
                _bronze_track_source_record(
                    options=options,
                    spotify_user_id=spotify_user_id,
                    track=track,
                    signal_source="saved_track",
                )
            )
            _add_track_and_artist_signals(
                track=track,
                track_signals=track_signals,
                artist_signals=artist_signals,
                options=options,
                spotify_user_id=spotify_user_id,
                spotify_account_id=spotify_account_id,
                signal_source="saved_track",
                track_weight=1.0,
                artist_weight=0.9,
            )

        for time_range in options.top_time_ranges:
            top_track_weight = _top_weight(time_range)
            top_tracks = list(
                self.spotify_client.iter_top_items(
                    "tracks",
                    limit_total=options.top_limit,
                    time_range=time_range,
                )
            )
            source_counts["top_tracks"] += len(top_tracks)
            for track in top_tracks:
                bronze_top_tracks.append(
                    _bronze_track_source_record(
                        options=options,
                        spotify_user_id=spotify_user_id,
                        track=track,
                        signal_source="top_track",
                        time_range=time_range,
                    )
                )
                _add_track_and_artist_signals(
                    track=track,
                    track_signals=track_signals,
                    artist_signals=artist_signals,
                    options=options,
                    spotify_user_id=spotify_user_id,
                    spotify_account_id=spotify_account_id,
                    signal_source="top_track",
                    track_weight=top_track_weight,
                    artist_weight=top_track_weight,
                    time_range=time_range,
                )

            top_artists = list(
                self.spotify_client.iter_top_items(
                    "artists",
                    limit_total=options.top_limit,
                    time_range=time_range,
                )
            )
            source_counts["top_artists"] += len(top_artists)
            for artist in top_artists:
                artist_name = _optional_str(artist.get("name"))
                if artist_name is None:
                    continue
                bronze_top_artists.append(
                    {
                        "run_id": options.run_id,
                        "source": "spotify",
                        "spotify_user_id": spotify_user_id,
                        "spotify_artist_id": _optional_str(artist.get("id")),
                        "artist_name": artist_name,
                        "signal_source": "top_artist",
                        "time_range": time_range,
                    }
                )
                artist_signals.add(
                    SpotifyProfileArtistSignalRecord(
                        spotify_user_id=spotify_user_id,
                        spotify_account_id=spotify_account_id,
                        spotify_artist_id=_optional_str(artist.get("id")),
                        artist_name=artist_name,
                        signal_source="top_artist",
                        time_range=time_range,
                        playlist_id=None,
                        playlist_name=None,
                        weight=_top_weight(time_range),
                        source_run_id=options.run_id,
                    )
                )

        if options.include_playlists and options.playlist_track_limit > 0:
            try:
                playlists = list(
                    self.spotify_client.iter_current_user_playlists(
                        limit_total=options.playlist_limit,
                    )
                )
            except ApiError as exc:
                if exc.status_code not in {401, 403}:
                    raise
                summary.notes.append("missing_optional_scope:playlist-read-private")
            else:
                selected_playlists = _selected_playlists(playlists, options.playlist_ids)
                source_counts["playlists"] = len(selected_playlists)
                remaining_playlist_tracks = options.playlist_track_limit
                for playlist in selected_playlists:
                    playlist_id = _optional_str(playlist.get("id"))
                    if playlist_id is None:
                        continue
                    playlist_name = _optional_str(playlist.get("name"))
                    bronze_playlists.append(
                        {
                            "run_id": options.run_id,
                            "source": "spotify",
                            "spotify_user_id": spotify_user_id,
                            "playlist_id": playlist_id,
                            "playlist_name": playlist_name,
                            "owner_id": _playlist_owner_id(playlist),
                        }
                    )
                    requested_track_count = min(
                        remaining_playlist_tracks,
                        options.playlist_track_limit,
                    )
                    if requested_track_count <= 0:
                        break
                    try:
                        playlist_items = list(
                            self.spotify_client.iter_playlist_items(
                                playlist_id,
                                limit_total=requested_track_count,
                                market=options.market,
                                fields=(
                                    "items(added_at,track(id,name,artists(id,name),duration_ms,"
                                    "explicit,popularity,external_ids,external_urls)),"
                                    "total,next,limit,offset"
                                ),
                            )
                        )
                    except ApiError as exc:
                        if exc.status_code not in {401, 403}:
                            raise
                        summary.notes.append(f"playlist_skipped_inaccessible:{playlist_id}")
                        continue
                    playlist_tracks = [
                        item["track"]
                        for item in playlist_items
                        if isinstance(item.get("track"), dict)
                    ]
                    source_counts["playlist_tracks"] += len(playlist_tracks)
                    remaining_playlist_tracks -= len(playlist_tracks)
                    weight = 0.6 if options.playlist_ids else 0.4
                    for track in playlist_tracks:
                        bronze_playlist_tracks.append(
                            _bronze_track_source_record(
                                options=options,
                                spotify_user_id=spotify_user_id,
                                track=track,
                                signal_source="playlist_track",
                                playlist_id=playlist_id,
                                playlist_name=playlist_name,
                            )
                        )
                        _add_track_and_artist_signals(
                            track=track,
                            track_signals=track_signals,
                            artist_signals=artist_signals,
                            options=options,
                            spotify_user_id=spotify_user_id,
                            spotify_account_id=spotify_account_id,
                            signal_source="playlist_track",
                            track_weight=weight,
                            artist_weight=weight,
                            playlist_id=playlist_id,
                            playlist_name=playlist_name,
                        )

        if options.include_recently_played and options.recently_played_limit > 0:
            try:
                recent_tracks = [
                    item["track"]
                    for item in _items(
                        self.spotify_client.get_recently_played(limit=options.recently_played_limit)
                    )
                    if isinstance(item.get("track"), dict)
                ]
            except ApiError as exc:
                if exc.status_code not in {401, 403}:
                    raise
                summary.notes.append("missing_optional_scope:user-read-recently-played")
            else:
                source_counts["recent_tracks"] = len(recent_tracks)
                for track in recent_tracks:
                    bronze_recent_tracks.append(
                        _bronze_track_source_record(
                            options=options,
                            spotify_user_id=spotify_user_id,
                            track=track,
                            signal_source="recent_track",
                        )
                    )
                    _add_track_and_artist_signals(
                        track=track,
                        track_signals=track_signals,
                        artist_signals=artist_signals,
                        options=options,
                        spotify_user_id=spotify_user_id,
                        spotify_account_id=spotify_account_id,
                        signal_source="recent_track",
                        track_weight=0.3,
                        artist_weight=0.3,
                    )

        track_signal_records = track_signals.records()
        artist_signal_records = artist_signals.records()
        interactions = [
            UserTrackInteractionRecord(
                user_id_hash=spotify_user_id,
                item_id=record.spotify_track_id,
                item_id_type="spotify_track_id",
                listen_count=1,
                first_listened_at=None,
                last_listened_at=None,
                implicit_rating=round(record.weight * 5.0, 3),
                source_run_id=options.run_id,
            )
            for record in track_signal_records
        ]

        self._write_outputs(
            options=options,
            current_user=_safe_user_profile_record(current_user, options.run_id),
            saved_tracks=bronze_saved_tracks,
            top_tracks=bronze_top_tracks,
            top_artists=bronze_top_artists,
            playlists=bronze_playlists,
            playlist_tracks=bronze_playlist_tracks,
            recent_tracks=bronze_recent_tracks,
            track_signals=[record.to_dict() for record in track_signal_records],
            artist_signals=[record.to_dict() for record in artist_signal_records],
            interactions=[record.to_dict() for record in interactions],
            summary=summary,
        )
        summary.counts.update(source_counts)
        summary.counts["track_signals"] = len(track_signal_records)
        summary.counts["artist_signals"] = len(artist_signal_records)
        summary.counts["profile_track_interactions"] = len(interactions)
        summary.notes.append(f"spotify_user_id:{spotify_user_id}")
        if spotify_account_id is not None:
            summary.notes.append("spotify_account_id_present:true")
        metadata_write = self.storage.write_json(
            run_metadata_key(options.run_id), summary.to_dict()
        )
        summary.outputs.append(metadata_write.uri)
        LOGGER.info(
            "Profile extraction finished run_id=%s counts=%s", options.run_id, summary.counts
        )
        return summary

    def _write_outputs(
        self,
        *,
        options: SpotifyProfileExtractionOptions,
        current_user: JsonDict,
        saved_tracks: list[JsonDict],
        top_tracks: list[JsonDict],
        top_artists: list[JsonDict],
        playlists: list[JsonDict],
        playlist_tracks: list[JsonDict],
        recent_tracks: list[JsonDict],
        track_signals: list[JsonDict],
        artist_signals: list[JsonDict],
        interactions: list[JsonDict],
        summary: ExtractionSummary,
    ) -> None:
        run_partition = f"run_id={options.run_id}"
        date_partition = f"dt={options.run_date}"
        writes = [
            self.storage.write_records(
                medallion_data_key(
                    "bronze", "spotify/user_profile", run_partition, options.file_format
                ),
                [current_user],
                file_format=options.file_format,
            ),
            self.storage.write_records(
                medallion_data_key(
                    "bronze", "spotify/saved_tracks", run_partition, options.file_format
                ),
                saved_tracks,
                file_format=options.file_format,
            ),
            self.storage.write_records(
                medallion_data_key(
                    "bronze", "spotify/top_tracks", run_partition, options.file_format
                ),
                top_tracks,
                file_format=options.file_format,
            ),
            self.storage.write_records(
                medallion_data_key(
                    "bronze", "spotify/top_artists", run_partition, options.file_format
                ),
                top_artists,
                file_format=options.file_format,
            ),
            self.storage.write_records(
                medallion_data_key(
                    "bronze", "spotify/playlists", run_partition, options.file_format
                ),
                playlists,
                file_format=options.file_format,
            ),
            self.storage.write_records(
                medallion_data_key(
                    "bronze", "spotify/playlist_tracks", run_partition, options.file_format
                ),
                playlist_tracks,
                file_format=options.file_format,
            ),
            self.storage.write_records(
                medallion_data_key(
                    "bronze", "spotify/recently_played", run_partition, options.file_format
                ),
                recent_tracks,
                file_format=options.file_format,
            ),
            self.storage.write_records(
                medallion_data_key(
                    "silver",
                    "user_profile_track_signals",
                    date_partition,
                    options.file_format,
                ),
                track_signals,
                file_format=options.file_format,
            ),
            self.storage.write_records(
                medallion_data_key(
                    "silver",
                    "user_profile_artist_signals",
                    date_partition,
                    options.file_format,
                ),
                artist_signals,
                file_format=options.file_format,
            ),
            self.storage.write_records(
                medallion_data_key(
                    "gold",
                    "user_profile_track_interactions",
                    date_partition,
                    options.file_format,
                ),
                interactions,
                file_format=options.file_format,
            ),
        ]
        summary.outputs.extend(write.uri for write in writes)


class _TrackSignalAccumulator:
    def __init__(self) -> None:
        self._records: dict[str, SpotifyProfileTrackSignalRecord] = {}
        self._order: list[str] = []

    def add(self, record: SpotifyProfileTrackSignalRecord) -> None:
        existing = self._records.get(record.spotify_track_id)
        if existing is None:
            self._order.append(record.spotify_track_id)
            self._records[record.spotify_track_id] = record
            return
        if record.weight > existing.weight:
            self._records[record.spotify_track_id] = record

    def records(self) -> list[SpotifyProfileTrackSignalRecord]:
        return [self._records[track_id] for track_id in self._order]


class _ArtistSignalAccumulator:
    def __init__(self) -> None:
        self._records: dict[str, SpotifyProfileArtistSignalRecord] = {}
        self._order: list[str] = []

    def add(self, record: SpotifyProfileArtistSignalRecord) -> None:
        existing = self._records.get(record.artist_name)
        if existing is None:
            self._order.append(record.artist_name)
            self._records[record.artist_name] = record
            return
        if record.weight > existing.weight:
            self._records[record.artist_name] = record

    def records(self) -> list[SpotifyProfileArtistSignalRecord]:
        return [self._records[artist_name] for artist_name in self._order]


def _add_track_and_artist_signals(
    *,
    track: JsonDict,
    track_signals: _TrackSignalAccumulator,
    artist_signals: _ArtistSignalAccumulator,
    options: SpotifyProfileExtractionOptions,
    spotify_user_id: str,
    spotify_account_id: str | None,
    signal_source: str,
    track_weight: float,
    artist_weight: float,
    time_range: str | None = None,
    playlist_id: str | None = None,
    playlist_name: str | None = None,
) -> None:
    track_id = _optional_str(track.get("id"))
    if track_id is None:
        return
    artist_names = _artist_names(track)
    track_signals.add(
        SpotifyProfileTrackSignalRecord(
            spotify_user_id=spotify_user_id,
            spotify_account_id=spotify_account_id,
            spotify_track_id=track_id,
            track_name=_optional_str(track.get("name")) or track_id,
            artist_names=artist_names,
            primary_artist_name=artist_names[0] if artist_names else None,
            signal_source=signal_source,
            time_range=time_range,
            playlist_id=playlist_id,
            playlist_name=playlist_name,
            weight=track_weight,
            source_run_id=options.run_id,
            spotify_url=_spotify_url(track),
            popularity=_optional_int(track.get("popularity")),
            explicit=_optional_bool(track.get("explicit")),
            duration_ms=_optional_int(track.get("duration_ms")),
            isrc=_track_isrc(track),
        )
    )
    for artist in _artists(track):
        artist_name = _optional_str(artist.get("name"))
        if artist_name is None:
            continue
        artist_signals.add(
            SpotifyProfileArtistSignalRecord(
                spotify_user_id=spotify_user_id,
                spotify_account_id=spotify_account_id,
                spotify_artist_id=_optional_str(artist.get("id")),
                artist_name=artist_name,
                signal_source=signal_source,
                time_range=time_range,
                playlist_id=playlist_id,
                playlist_name=playlist_name,
                weight=artist_weight,
                source_run_id=options.run_id,
            )
        )


def _bronze_track_source_record(
    *,
    options: SpotifyProfileExtractionOptions,
    spotify_user_id: str,
    track: JsonDict,
    signal_source: str,
    time_range: str | None = None,
    playlist_id: str | None = None,
    playlist_name: str | None = None,
) -> JsonDict:
    track_id = _optional_str(track.get("id"))
    return {
        "run_id": options.run_id,
        "source": "spotify",
        "spotify_user_id": spotify_user_id,
        "spotify_track_id": track_id,
        "track_name": _optional_str(track.get("name")),
        "artist_names": _artist_names(track),
        "primary_artist_name": _artist_names(track)[0] if _artist_names(track) else None,
        "signal_source": signal_source,
        "time_range": time_range,
        "playlist_id": playlist_id,
        "playlist_name": playlist_name,
        "duration_ms": _optional_int(track.get("duration_ms")),
        "explicit": _optional_bool(track.get("explicit")),
        "popularity": _optional_int(track.get("popularity")),
        "isrc": _track_isrc(track),
        "spotify_url": _spotify_url(track),
    }


def _safe_user_profile_record(current_user: JsonDict, run_id: str) -> JsonDict:
    return {
        "run_id": run_id,
        "source": "spotify",
        "spotify_user_id": _optional_str(current_user.get("id")),
        "spotify_account_id_present": current_user.get("account_id") is not None,
        "country": _optional_str(current_user.get("country")),
        "product": _optional_str(current_user.get("product")),
    }


def _items(payload: JsonDict) -> list[JsonDict]:
    items = payload.get("items", [])
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def _selected_playlists(
    playlists: list[JsonDict],
    playlist_ids: tuple[str, ...],
) -> list[JsonDict]:
    if not playlist_ids:
        return playlists
    by_id = {
        str(playlist["id"]): playlist
        for playlist in playlists
        if _optional_str(playlist.get("id")) is not None
    }
    return [
        by_id.get(playlist_id, {"id": playlist_id, "name": None, "owner": {}})
        for playlist_id in playlist_ids
    ]


def _playlist_owner_id(playlist: JsonDict) -> str | None:
    owner = playlist.get("owner")
    if not isinstance(owner, dict):
        return None
    return _optional_str(owner.get("id"))


def _artists(track: JsonDict) -> list[JsonDict]:
    artists = track.get("artists", [])
    if not isinstance(artists, list):
        return []
    return [artist for artist in artists if isinstance(artist, dict)]


def _artist_names(track: JsonDict) -> list[str]:
    return [str(artist["name"]) for artist in _artists(track) if artist.get("name")]


def _spotify_url(track: JsonDict) -> str | None:
    external_urls = track.get("external_urls")
    if not isinstance(external_urls, dict):
        return None
    return _optional_str(external_urls.get("spotify"))


def _track_isrc(track: JsonDict) -> str | None:
    external_ids = track.get("external_ids")
    if not isinstance(external_ids, dict):
        return None
    return _optional_str(external_ids.get("isrc"))


def _top_weight(time_range: str) -> float:
    return {
        "short_term": 0.9,
        "medium_term": 0.8,
        "long_term": 0.7,
    }.get(time_range, 0.8)


def _empty_source_counts() -> dict[str, int]:
    return {
        "saved_tracks": 0,
        "top_tracks": 0,
        "top_artists": 0,
        "playlists": 0,
        "playlist_tracks": 0,
        "recent_tracks": 0,
    }


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        if isinstance(value, int | float | str | bytes | bytearray):
            return int(value)
    except (TypeError, ValueError):
        return None
    return None


def _optional_bool(value: object) -> bool | None:
    if value is None:
        return None
    return bool(value)
