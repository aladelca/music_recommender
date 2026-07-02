from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from music_recommender.recommender.data import (
    MissingRecommenderDataError,
    check_local_recommender_data,
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


def write_table(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(rows)
    pq.write_table(table, path)  # type: ignore[no-untyped-call]
