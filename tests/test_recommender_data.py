from __future__ import annotations

from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from music_recommender.recommender.catalog import load_recommender_catalog_from_run
from music_recommender.recommender.data import (
    MissingRecommenderDataError,
    check_local_recommender_data,
    check_s3_recommender_data,
    read_dataset_records,
)


def test_check_local_recommender_data_reads_required_parquet_outputs(tmp_path: Path) -> None:
    write_table(
        tmp_path / "run-1" / "silver" / "tracks" / "dt=2026-05-22" / "part-000.parquet",
        [{"spotify_track_id": "track-1"}, {"spotify_track_id": "track-2"}],
    )
    write_table(
        tmp_path / "run-1" / "silver" / "audio_features" / "dt=2026-05-22" / "part-000.parquet",
        [{"spotify_track_id": "track-1"}],
    )

    summary = check_local_recommender_data(tmp_path, run_id="run-1")

    assert summary.ready is True
    assert summary.run_id == "run-1"
    assert summary.datasets["silver/tracks"].row_count == 2
    assert summary.datasets["silver/audio_features"].row_count == 1


def test_check_local_recommender_data_fails_when_required_dataset_is_missing(
    tmp_path: Path,
) -> None:
    write_table(
        tmp_path / "run-1" / "silver" / "tracks" / "dt=2026-05-22" / "part-000.parquet",
        [{"spotify_track_id": "track-1"}],
    )

    with pytest.raises(MissingRecommenderDataError, match="silver/audio_features"):
        check_local_recommender_data(tmp_path, run_id="run-1")


def test_check_local_recommender_data_can_pick_a_run_with_required_datasets(
    tmp_path: Path,
) -> None:
    write_table(
        tmp_path
        / "run-without-features"
        / "silver"
        / "tracks"
        / "dt=2026-05-22"
        / "part-000.parquet",
        [{"spotify_track_id": "track-1"}],
    )
    write_table(
        tmp_path / "run-ready" / "silver" / "tracks" / "dt=2026-05-22" / "part-000.parquet",
        [{"spotify_track_id": "track-1"}],
    )
    write_table(
        tmp_path / "run-ready" / "silver" / "audio_features" / "dt=2026-05-22" / "part-000.parquet",
        [{"spotify_track_id": "track-1"}],
    )

    summary = check_local_recommender_data(tmp_path)

    assert summary.run_id == "run-ready"


def test_load_recommender_catalog_from_run_merges_tracks_features_and_interactions(
    tmp_path: Path,
) -> None:
    write_table(
        tmp_path / "catalog-run" / "silver" / "tracks" / "dt=2026-05-22" / "part-000.parquet",
        [
            {
                "spotify_track_id": "track-1",
                "track_name": "Sunny Recovery",
                "artist_names": ["Artist A"],
                "primary_artist_name": "Artist A",
                "explicit": False,
                "popularity": 80,
                "spotify_url": "https://open.spotify.com/track/track-1",
                "seed_artist": "Artist A",
            },
            {
                "spotify_track_id": "track-2",
                "track_name": "Quiet Night",
                "artist_names": ["Artist B"],
                "primary_artist_name": "Artist B",
                "explicit": False,
                "popularity": 35,
                "spotify_url": "https://open.spotify.com/track/track-2",
                "seed_artist": "Artist B",
            },
        ],
    )
    write_table(
        tmp_path
        / "catalog-run"
        / "silver"
        / "audio_features"
        / "dt=2026-05-22"
        / "part-000.parquet",
        [
            {
                "spotify_track_id": "track-1",
                "danceability": 0.82,
                "energy": 0.76,
                "valence": 0.91,
                "tempo": 118.0,
            }
        ],
    )
    write_table(
        tmp_path / "catalog-run" / "silver" / "lyrics_nlp" / "dt=2026-05-22" / "part-000.parquet",
        [
            {
                "spotify_track_id": "track-1",
                "sentiment_label": "positive",
                "positive_score": 0.84,
                "negative_score": 0.05,
                "neutral_score": 0.11,
            }
        ],
    )
    write_table(
        tmp_path
        / "network-run"
        / "gold"
        / "catalog_user_track_interactions"
        / "dt=2026-05-22"
        / "part-000.parquet",
        [
            {
                "user_id_hash": "user-1",
                "item_id": "track-1",
                "item_id_type": "catalog_spotify_track_id",
                "listen_count": 4,
                "implicit_rating": 2.7,
            }
        ],
    )

    catalog = load_recommender_catalog_from_run(
        tmp_path,
        catalog_run_id="catalog-run",
        interaction_run_id="network-run",
    )

    assert len(catalog.tracks) == 2
    track = catalog.by_track_id["track-1"]
    assert track.name == "Sunny Recovery"
    assert track.audio_features is not None
    assert track.audio_features.valence == 0.91
    assert track.lyrics_sentiment_label == "positive"
    assert track.interaction_count == 1
    assert track.max_implicit_rating == 2.7


def test_load_recommender_catalog_from_run_requires_core_datasets(tmp_path: Path) -> None:
    write_table(
        tmp_path / "catalog-run" / "silver" / "tracks" / "dt=2026-05-22" / "part-000.parquet",
        [{"spotify_track_id": "track-1"}],
    )

    with pytest.raises(MissingRecommenderDataError, match="silver/audio_features"):
        load_recommender_catalog_from_run(tmp_path, catalog_run_id="catalog-run")


def test_load_recommender_catalog_from_run_supports_s3_medallion_partitions() -> None:
    fake_s3 = FakeS3Client()
    fake_s3.add_parquet(
        "bucket",
        "silver/tracks/run_id=catalog-run/part-000.parquet",
        [
            {
                "spotify_track_id": "track-1",
                "track_name": "Cloud Recovery",
                "artist_names": ["Artist A"],
                "primary_artist_name": "Artist A",
                "explicit": False,
                "popularity": 88,
                "spotify_url": "https://open.spotify.com/track/track-1",
            }
        ],
    )
    fake_s3.add_parquet(
        "bucket",
        "silver/audio_features/run_id=catalog-run/part-000.parquet",
        [{"spotify_track_id": "track-1", "valence": 0.93}],
    )
    fake_s3.add_parquet(
        "bucket",
        "gold/catalog_user_track_interactions/run_id=network-run/part-000.parquet",
        [{"item_id": "track-1", "implicit_rating": 4.2}],
    )

    catalog = load_recommender_catalog_from_run(
        "s3://bucket",
        catalog_run_id="catalog-run",
        interaction_run_id="network-run",
        s3_client=fake_s3,
    )

    track = catalog.by_track_id["track-1"]
    assert track.name == "Cloud Recovery"
    assert track.audio_features is not None
    assert track.audio_features.valence == 0.93
    assert track.interaction_count == 1
    assert track.max_implicit_rating == 4.2


def test_load_recommender_catalog_from_run_reads_s3_dt_partitions_by_source_run_id() -> None:
    fake_s3 = FakeS3Client()
    fake_s3.add_parquet(
        "bucket",
        "silver/tracks/dt=2026-07-09/part-000.parquet",
        [
            {
                "spotify_track_id": "target-track",
                "track_name": "Profile Signal",
                "artist_names": ["Target Artist"],
                "primary_artist_name": "Target Artist",
                "source_run_id": "catalog-run",
            },
            {
                "spotify_track_id": "other-track",
                "track_name": "Wrong Run",
                "artist_names": ["Other Artist"],
                "primary_artist_name": "Other Artist",
                "source_run_id": "other-run",
            },
        ],
    )
    fake_s3.add_parquet(
        "bucket",
        "silver/audio_features/dt=2026-07-09/part-000.parquet",
        [
            {"spotify_track_id": "target-track", "valence": 0.91, "source_run_id": "catalog-run"},
            {"spotify_track_id": "other-track", "valence": 0.1, "source_run_id": "other-run"},
        ],
    )
    fake_s3.add_parquet(
        "bucket",
        "gold/catalog_user_track_interactions/dt=2026-07-09/part-000.parquet",
        [
            {"item_id": "target-track", "implicit_rating": 3.5, "source_run_id": "network-run"},
            {"item_id": "other-track", "implicit_rating": 5.0, "source_run_id": "other-run"},
        ],
    )

    catalog = load_recommender_catalog_from_run(
        "s3://bucket",
        catalog_run_id="catalog-run",
        interaction_run_id="network-run",
        s3_client=fake_s3,
    )

    assert tuple(track.id for track in catalog.tracks) == ("target-track",)
    track = catalog.by_track_id["target-track"]
    assert track.audio_features is not None
    assert track.audio_features.valence == 0.91
    assert track.interaction_count == 1
    assert track.max_implicit_rating == 3.5


def test_check_s3_recommender_data_filters_required_datasets_by_source_run_id() -> None:
    fake_s3 = FakeS3Client()
    fake_s3.add_parquet(
        "bucket",
        "silver/tracks/dt=2026-07-09/part-000.parquet",
        [
            {"spotify_track_id": "target-track", "source_run_id": "catalog-run"},
            {"spotify_track_id": "other-track", "source_run_id": "other-run"},
        ],
    )
    fake_s3.add_parquet(
        "bucket",
        "silver/audio_features/dt=2026-07-09/part-000.parquet",
        [
            {"spotify_track_id": "target-track", "source_run_id": "catalog-run"},
            {"spotify_track_id": "other-track", "source_run_id": "other-run"},
        ],
    )

    summary = check_s3_recommender_data(
        "s3://bucket",
        run_id="catalog-run",
        s3_client=fake_s3,
    )

    assert summary.ready is True
    assert summary.datasets["silver/tracks"].row_count == 1
    assert summary.datasets["silver/audio_features"].row_count == 1


def test_read_dataset_records_supports_s3_parquet_and_jsonl() -> None:
    fake_s3 = FakeS3Client()
    fake_s3.add_parquet(
        "bucket",
        "catalog/silver/tracks/part-000.parquet",
        [{"spotify_track_id": "track-1"}],
    )
    fake_s3.add_jsonl(
        "bucket",
        "catalog/silver/tracks/part-001.jsonl",
        [{"spotify_track_id": "track-2"}],
    )

    records = read_dataset_records("s3://bucket/catalog/silver/tracks", s3_client=fake_s3)

    assert [record["spotify_track_id"] for record in records] == ["track-1", "track-2"]


def write_table(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(rows)
    pq.write_table(table, path)  # type: ignore[no-untyped-call]


class FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}

    def add_parquet(self, bucket: str, key: str, rows: list[dict[str, Any]]) -> None:
        sink = pa.BufferOutputStream()
        pq.write_table(pa.Table.from_pylist(rows), sink)  # type: ignore[no-untyped-call]
        self.objects[(bucket, key)] = sink.getvalue().to_pybytes()

    def add_jsonl(self, bucket: str, key: str, rows: list[dict[str, Any]]) -> None:
        import json

        body = "".join(json.dumps(row) + "\n" for row in rows)
        self.objects[(bucket, key)] = body.encode("utf-8")

    def list_objects_v2(self, *, Bucket: str, Prefix: str) -> dict[str, object]:
        contents = [
            {"Key": key}
            for bucket, key in sorted(self.objects)
            if bucket == Bucket and key.startswith(Prefix)
        ]
        return {"Contents": contents}

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        from io import BytesIO

        return {"Body": BytesIO(self.objects[(Bucket, Key)])}
