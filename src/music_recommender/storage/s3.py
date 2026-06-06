from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, Literal

import boto3
import pyarrow as pa
import pyarrow.parquet as pq

LOGGER = logging.getLogger(__name__)
FileFormat = Literal["jsonl", "parquet"]


@dataclass(frozen=True)
class WriteResult:
    uri: str
    key: str
    count: int


class S3Storage:
    def __init__(
        self,
        *,
        bucket: str | None,
        dry_run: bool = False,
        local_root: Path | str = "data/dry-run",
        s3_client: Any | None = None,
    ) -> None:
        if not dry_run and not bucket:
            raise ValueError("bucket is required when dry_run is false")
        self.bucket = bucket
        self.dry_run = dry_run
        self.local_root = Path(local_root)
        self.s3_client = s3_client or (None if dry_run else boto3.client("s3"))

    def write_jsonl(self, key: str, records: Iterable[Mapping[str, Any]]) -> WriteResult:
        rows = list(records)
        body = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows)
        self._write_body(key, body, "application/x-ndjson")
        return WriteResult(uri=self._uri(key), key=key, count=len(rows))

    def write_parquet(self, key: str, records: Iterable[Mapping[str, Any]]) -> WriteResult:
        rows = [_coerce_record_for_parquet(record) for record in records]
        table = pa.Table.from_pylist(rows)
        buffer = BytesIO()
        pq.write_table(table, buffer)  # type: ignore[no-untyped-call]
        self._write_bytes(key, buffer.getvalue(), "application/vnd.apache.parquet")
        return WriteResult(uri=self._uri(key), key=key, count=len(rows))

    def write_records(
        self,
        key: str,
        records: Iterable[Mapping[str, Any]],
        *,
        file_format: FileFormat,
    ) -> WriteResult:
        if file_format == "jsonl":
            return self.write_jsonl(key, records)
        if file_format == "parquet":
            return self.write_parquet(key, records)
        raise ValueError(f"Unsupported file format: {file_format}")

    def write_json(self, key: str, payload: Mapping[str, Any]) -> WriteResult:
        body = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        self._write_body(key, body, "application/json")
        return WriteResult(uri=self._uri(key), key=key, count=1)

    def _write_body(self, key: str, body: str, content_type: str) -> None:
        self._write_bytes(key, body.encode("utf-8"), content_type)

    def _write_bytes(self, key: str, body: bytes, content_type: str) -> None:
        if self.dry_run:
            target = self.local_root / key
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(body)
            LOGGER.debug("Wrote local object %s", target)
            return

        if self.s3_client is None or self.bucket is None:
            raise ValueError("S3 client and bucket are required for S3 writes")
        self.s3_client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=body,
            ContentType=content_type,
        )
        LOGGER.debug("Uploaded S3 object s3://%s/%s", self.bucket, key)

    def _uri(self, key: str) -> str:
        if self.dry_run:
            return str(self.local_root / key)
        return f"s3://{self.bucket}/{key}"


def medallion_jsonl_key(layer: str, dataset: str, partition: str) -> str:
    return medallion_data_key(layer, dataset, partition, "jsonl")


def medallion_data_key(
    layer: str,
    dataset: str,
    partition: str,
    file_format: FileFormat,
) -> str:
    extension = "jsonl" if file_format == "jsonl" else "parquet"
    return f"{layer}/{dataset}/{partition}/part-000.{extension}"


def run_metadata_key(run_id: str) -> str:
    return f"metadata/runs/run_id={run_id}.json"


def _coerce_record_for_parquet(record: Mapping[str, Any]) -> dict[str, Any]:
    return {key: _coerce_value_for_parquet(value) for key, value in record.items()}


def _coerce_value_for_parquet(value: Any) -> Any:
    if isinstance(value, Mapping):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        if all(_is_scalar(item) for item in value):
            return list(value)
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value


def _is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, str | int | float | bool)
