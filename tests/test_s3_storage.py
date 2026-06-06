from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from music_recommender.storage.s3 import (
    S3Storage,
    medallion_data_key,
    medallion_jsonl_key,
    run_metadata_key,
)


class FakeS3Client:
    def __init__(self) -> None:
        self.objects: list[dict[str, Any]] = []

    def put_object(self, **kwargs: Any) -> None:
        self.objects.append(kwargs)


def test_local_jsonl_write(tmp_path: Path) -> None:
    storage = S3Storage(bucket=None, dry_run=True, local_root=tmp_path)
    key = medallion_jsonl_key("bronze", "spotify/tracks", "run_id=run-1")

    result = storage.write_jsonl(key, [{"a": 1}, {"b": 2}])

    assert result.count == 2
    output = tmp_path / key
    assert output.exists()
    assert [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()] == [
        {"a": 1},
        {"b": 2},
    ]


def test_s3_json_write() -> None:
    fake = FakeS3Client()
    storage = S3Storage(bucket="bucket", dry_run=False, s3_client=fake)

    result = storage.write_json(run_metadata_key("run-1"), {"ok": True})

    assert result.uri == "s3://bucket/metadata/runs/run_id=run-1.json"
    assert fake.objects[0]["Bucket"] == "bucket"
    assert fake.objects[0]["ContentType"] == "application/json"


def test_local_parquet_write(tmp_path: Path) -> None:
    storage = S3Storage(bucket=None, dry_run=True, local_root=tmp_path)
    key = medallion_data_key("silver", "tracks", "dt=2026-05-21", "parquet")

    result = storage.write_records(
        key,
        [{"spotify_track_id": "track-1", "artist_names": ["Artist"], "raw": {"a": 1}}],
        file_format="parquet",
    )

    output = tmp_path / key
    assert result.count == 1
    assert output.exists()
    table = pq.read_table(output)  # type: ignore[no-untyped-call]
    assert table.to_pylist() == [
        {
            "spotify_track_id": "track-1",
            "artist_names": ["Artist"],
            "raw": '{"a": 1}',
            "dt": "2026-05-21",
        }
    ]


def test_s3_parquet_write() -> None:
    fake = FakeS3Client()
    storage = S3Storage(bucket="bucket", dry_run=False, s3_client=fake)
    key = medallion_data_key("silver", "tracks", "dt=2026-05-21", "parquet")

    result = storage.write_records(key, [{"a": 1}], file_format="parquet")

    assert result.uri == "s3://bucket/silver/tracks/dt=2026-05-21/part-000.parquet"
    assert fake.objects[0]["ContentType"] == "application/vnd.apache.parquet"
    assert isinstance(fake.objects[0]["Body"], bytes)
