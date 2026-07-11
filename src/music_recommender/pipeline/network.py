from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from music_recommender.models import (
    ExtractionSummary,
    JsonDict,
    LinkedListenRecord,
    ListenBrainzListenRecord,
    UserTrackInteractionRecord,
)
from music_recommender.normalization import normalize_lookup_key
from music_recommender.sources.listenbrainz import ListenBrainzDumpReader
from music_recommender.storage.s3 import FileFormat, S3Storage, medallion_data_key, run_metadata_key

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class NetworkExtractionOptions:
    dump_path: Path
    run_id: str
    run_date: str
    file_format: FileFormat
    user_hash_salt: str = ""
    limit: int | None = None
    catalog_tracks_path: Path | None = None
    catalog_run_id: str | None = None


class NetworkExtractor:
    def __init__(
        self,
        *,
        listenbrainz: ListenBrainzDumpReader,
        storage: S3Storage,
    ) -> None:
        self.listenbrainz = listenbrainz
        self.storage = storage

    def run(self, options: NetworkExtractionOptions) -> ExtractionSummary:
        summary = ExtractionSummary(run_id=options.run_id)
        listens = list(
            self.listenbrainz.iter_listens(
                options.dump_path,
                run_id=options.run_id,
                user_hash_salt=options.user_hash_salt,
                limit=options.limit,
            )
        )
        interactions = aggregate_user_track_interactions(listens, options.run_id)
        linked_listens: list[LinkedListenRecord] = []
        catalog_interactions: list[UserTrackInteractionRecord] = []
        if options.catalog_tracks_path is not None:
            catalog_tracks = load_catalog_tracks(options.catalog_tracks_path)
            linked_listens = link_listens_to_catalog(listens, catalog_tracks)
            catalog_interactions = aggregate_linked_listens(linked_listens, options.run_id)

        run_partition = f"run_id={options.run_id}"
        date_partition = f"dt={options.run_date}"

        writes = [
            self.storage.write_records(
                medallion_data_key(
                    "bronze", "network/listenbrainz", run_partition, options.file_format
                ),
                [record.to_dict() for record in listens],
                file_format=options.file_format,
            ),
            self.storage.write_records(
                medallion_data_key(
                    "silver", "network/listens", date_partition, options.file_format
                ),
                [record.to_dict() for record in listens],
                file_format=options.file_format,
            ),
            self.storage.write_records(
                medallion_data_key(
                    "gold", "user_track_interactions", date_partition, options.file_format
                ),
                [record.to_dict() for record in interactions],
                file_format=options.file_format,
            ),
            self.storage.write_records(
                medallion_data_key(
                    "silver", "network/listens_linked", date_partition, options.file_format
                ),
                [record.to_dict() for record in linked_listens],
                file_format=options.file_format,
            ),
            self.storage.write_records(
                medallion_data_key(
                    "gold",
                    "catalog_user_track_interactions",
                    date_partition,
                    options.file_format,
                ),
                [record.to_dict() for record in catalog_interactions],
                file_format=options.file_format,
            ),
        ]
        summary.outputs.extend(write.uri for write in writes)
        summary.counts.update(
            {
                "listenbrainz_listens": len(listens),
                "user_track_interactions": len(interactions),
                "catalog_linked_listens": len(linked_listens),
                "catalog_user_track_interactions": len(catalog_interactions),
            }
        )
        if options.catalog_tracks_path is not None:
            summary.notes.append(f"catalog_tracks_path:{options.catalog_tracks_path}")
        if options.catalog_run_id is not None:
            summary.notes.append(f"catalog_run_id:{options.catalog_run_id}")
        metadata_write = self.storage.write_json(
            run_metadata_key(options.run_id), summary.to_dict()
        )
        summary.outputs.append(metadata_write.uri)
        LOGGER.info(
            "Network extraction finished run_id=%s counts=%s", options.run_id, summary.counts
        )
        return summary


def aggregate_user_track_interactions(
    listens: list[ListenBrainzListenRecord],
    run_id: str,
) -> list[UserTrackInteractionRecord]:
    grouped: dict[tuple[str, str, str], list[ListenBrainzListenRecord]] = {}
    for listen in listens:
        item_id, item_id_type = listen_item_id(listen)
        if item_id is None or item_id_type is None:
            continue
        grouped.setdefault((listen.user_id_hash, item_id, item_id_type), []).append(listen)

    interactions: list[UserTrackInteractionRecord] = []
    for (user_id_hash, item_id, item_id_type), group in grouped.items():
        listened_values = [listen.listened_at for listen in group if listen.listened_at is not None]
        listen_count = len(group)
        interactions.append(
            UserTrackInteractionRecord(
                user_id_hash=user_id_hash,
                item_id=item_id,
                item_id_type=item_id_type,
                listen_count=listen_count,
                first_listened_at=min(listened_values) if listened_values else None,
                last_listened_at=max(listened_values) if listened_values else None,
                implicit_rating=implicit_rating_from_count(listen_count),
                source_run_id=run_id,
            )
        )
    return interactions


def aggregate_linked_listens(
    linked_listens: list[LinkedListenRecord],
    run_id: str,
) -> list[UserTrackInteractionRecord]:
    listens = [
        ListenBrainzListenRecord(
            user_id_hash=listen.user_id_hash,
            listened_at=listen.listened_at,
            recording_mbid=None,
            artist_name=listen.catalog_primary_artist_name,
            track_name=listen.catalog_track_name,
            release_name=None,
            isrc=None,
            spotify_track_id=listen.catalog_spotify_track_id,
            source=listen.source,
            source_run_id=listen.source_run_id,
        )
        for listen in linked_listens
    ]
    interactions = aggregate_user_track_interactions(listens, run_id)
    return [
        UserTrackInteractionRecord(
            user_id_hash=interaction.user_id_hash,
            item_id=interaction.item_id,
            item_id_type="catalog_spotify_track_id",
            listen_count=interaction.listen_count,
            first_listened_at=interaction.first_listened_at,
            last_listened_at=interaction.last_listened_at,
            implicit_rating=interaction.implicit_rating,
            source_run_id=interaction.source_run_id,
        )
        for interaction in interactions
    ]


def load_catalog_tracks(path: Path) -> list[JsonDict]:
    paths = _catalog_data_files(path)
    tracks: list[JsonDict] = []
    for data_path in paths:
        if data_path.suffix == ".parquet":
            tracks.extend(_read_parquet_records(data_path))
        elif data_path.suffix == ".jsonl":
            tracks.extend(_read_jsonl_records(data_path))
    return tracks


def link_listens_to_catalog(
    listens: list[ListenBrainzListenRecord],
    catalog_tracks: list[JsonDict],
) -> list[LinkedListenRecord]:
    index = CatalogTrackIndex(catalog_tracks)
    linked: list[LinkedListenRecord] = []
    for listen in listens:
        match = index.match(listen)
        if match is None:
            continue
        catalog_track, method = match
        catalog_spotify_track_id = _optional_str(catalog_track.get("spotify_track_id"))
        if catalog_spotify_track_id is None:
            continue
        item_id, item_id_type = listen_item_id(listen)
        linked.append(
            LinkedListenRecord(
                user_id_hash=listen.user_id_hash,
                listened_at=listen.listened_at,
                spotify_track_id=item_id,
                item_id_type=item_id_type,
                artist_name=listen.artist_name,
                track_name=listen.track_name,
                catalog_spotify_track_id=catalog_spotify_track_id,
                catalog_track_name=_optional_str(catalog_track.get("track_name")),
                catalog_primary_artist_name=_optional_str(catalog_track.get("primary_artist_name")),
                catalog_match_method=method,
                source=listen.source,
                source_run_id=listen.source_run_id,
            )
        )
    return linked


class CatalogTrackIndex:
    def __init__(self, tracks: list[JsonDict]) -> None:
        self.by_spotify_id: dict[str, JsonDict] = {}
        self.by_isrc: dict[str, JsonDict] = {}
        self.by_artist_title: dict[str, JsonDict] = {}
        for track in tracks:
            spotify_track_id = _optional_str(track.get("spotify_track_id"))
            if spotify_track_id:
                self.by_spotify_id.setdefault(spotify_track_id, track)
            isrc = _optional_str(track.get("isrc"))
            if isrc:
                self.by_isrc.setdefault(isrc.upper(), track)
            key = artist_title_key(
                _optional_str(track.get("primary_artist_name")),
                _optional_str(track.get("track_name")),
            )
            if key:
                self.by_artist_title.setdefault(key, track)

    def match(self, listen: ListenBrainzListenRecord) -> tuple[JsonDict, str] | None:
        if listen.spotify_track_id and listen.spotify_track_id in self.by_spotify_id:
            return self.by_spotify_id[listen.spotify_track_id], "spotify_track_id"
        if listen.isrc and listen.isrc.upper() in self.by_isrc:
            return self.by_isrc[listen.isrc.upper()], "isrc"
        key = artist_title_key(listen.artist_name, listen.track_name)
        if key and key in self.by_artist_title:
            return self.by_artist_title[key], "artist_track_name"
        return None


def listen_item_id(listen: ListenBrainzListenRecord) -> tuple[str | None, str | None]:
    if listen.spotify_track_id:
        return listen.spotify_track_id, "spotify_track_id"
    if listen.isrc:
        return listen.isrc, "isrc"
    if listen.recording_mbid:
        return listen.recording_mbid, "recording_mbid"
    if listen.artist_name and listen.track_name:
        return f"{listen.artist_name.lower()}::{listen.track_name.lower()}", "artist_track_name"
    return None, None


def artist_title_key(artist_name: str | None, track_name: str | None) -> str | None:
    if not artist_name or not track_name:
        return None
    return f"{normalize_lookup_key(artist_name)}::{normalize_lookup_key(track_name)}"


def implicit_rating_from_count(listen_count: int) -> float:
    if listen_count <= 0:
        return 0.0
    rating = 1.0 + math.sqrt(float(listen_count - 1))
    return float(min(5.0, rating))


def _catalog_data_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted(
        [data_path for data_path in path.rglob("*") if data_path.suffix in {".parquet", ".jsonl"}]
    )


def _read_parquet_records(path: Path) -> list[JsonDict]:
    import pyarrow.parquet as pq

    table = pq.read_table(path)  # type: ignore[no-untyped-call]
    return [dict(record) for record in table.to_pylist()]


def _read_jsonl_records(path: Path) -> list[JsonDict]:
    import json

    rows: list[JsonDict] = []
    with path.open(encoding="utf-8") as file:
        for line in file:
            if line.strip():
                payload: Any = json.loads(line)
                if isinstance(payload, dict):
                    rows.append(payload)
    return rows


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
