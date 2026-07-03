from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pyarrow.parquet as pq

JsonReadyDict = dict[str, object]
JsonDict = dict[str, Any]

REQUIRED_READINESS_DATASETS = ("silver/tracks", "silver/audio_features")


class MissingRecommenderDataError(ValueError):
    pass


@dataclass(frozen=True)
class DatasetReadiness:
    dataset: str
    path: str
    file_count: int
    row_count: int

    def to_dict(self) -> JsonReadyDict:
        return asdict(self)


@dataclass(frozen=True)
class RecommenderDataReadiness:
    root: str
    run_id: str
    datasets: dict[str, DatasetReadiness]

    @property
    def ready(self) -> bool:
        return all(dataset.row_count > 0 for dataset in self.datasets.values())

    def to_dict(self) -> JsonReadyDict:
        return {
            "root": self.root,
            "run_id": self.run_id,
            "ready": self.ready,
            "datasets": {
                name: dataset.to_dict() for name, dataset in sorted(self.datasets.items())
            },
        }


def check_local_recommender_data(
    data_root: Path | str,
    *,
    run_id: str | None = None,
    required_datasets: tuple[str, ...] = REQUIRED_READINESS_DATASETS,
) -> RecommenderDataReadiness:
    root = Path(data_root)
    if run_id is not None:
        return _check_run(root=root, run_id=run_id, required_datasets=required_datasets)

    missing_messages: list[str] = []
    for candidate in _candidate_run_dirs(root):
        try:
            return _check_run(
                root=root,
                run_id=candidate.name,
                required_datasets=required_datasets,
            )
        except MissingRecommenderDataError as error:
            missing_messages.append(str(error))

    if missing_messages:
        raise MissingRecommenderDataError(
            "No local recommender run contains all required datasets. "
            f"Last error: {missing_messages[-1]}"
        )
    raise MissingRecommenderDataError(f"No local recommender runs found under {root}")


def read_dataset_records(
    location: Path | str,
    *,
    s3_client: Any | None = None,
) -> list[JsonDict]:
    location_text = str(location)
    if location_text.startswith("s3://"):
        return _read_s3_records(location_text, s3_client=s3_client)

    records: list[JsonDict] = []
    for data_file in _data_files(Path(location)):
        records.extend(_read_data_file(data_file))
    return records


def _check_run(
    *,
    root: Path,
    run_id: str,
    required_datasets: tuple[str, ...],
) -> RecommenderDataReadiness:
    run_root = root / run_id
    if not run_root.exists():
        raise MissingRecommenderDataError(f"Run does not exist: {run_root}")

    datasets = {
        dataset: _summarize_dataset(run_root=run_root, dataset=dataset)
        for dataset in required_datasets
    }
    return RecommenderDataReadiness(root=str(root), run_id=run_id, datasets=datasets)


def _candidate_run_dirs(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted([path for path in root.iterdir() if path.is_dir()], key=lambda path: path.name)


def _summarize_dataset(*, run_root: Path, dataset: str) -> DatasetReadiness:
    dataset_path = run_root / dataset
    files = _data_files(dataset_path)
    if not files:
        raise MissingRecommenderDataError(f"Missing required recommender dataset: {dataset}")
    return DatasetReadiness(
        dataset=dataset,
        path=str(dataset_path),
        file_count=len(files),
        row_count=sum(_row_count(file) for file in files),
    )


def _data_files(path: Path) -> list[Path]:
    if path.is_file() and path.suffix in {".parquet", ".jsonl"}:
        return [path]
    if not path.exists():
        return []
    return sorted(file for file in path.rglob("*") if file.suffix in {".parquet", ".jsonl"})


def _row_count(path: Path) -> int:
    if path.suffix == ".parquet":
        parquet_file = pq.ParquetFile(path)  # type: ignore[no-untyped-call]
        metadata = parquet_file.metadata
        return int(metadata.num_rows) if metadata is not None else 0
    if path.suffix == ".jsonl":
        return _jsonl_row_count(path)
    raise ValueError(f"Unsupported data file format: {path}")


def _read_data_file(path: Path) -> list[JsonDict]:
    if path.suffix == ".parquet":
        table = pq.read_table(path)  # type: ignore[no-untyped-call]
        return [dict(record) for record in table.to_pylist()]
    if path.suffix == ".jsonl":
        return _read_jsonl_records(path)
    raise ValueError(f"Unsupported data file format: {path}")


def _read_jsonl_records(path: Path) -> list[JsonDict]:
    rows: list[JsonDict] = []
    with path.open(encoding="utf-8") as file:
        for line in file:
            if line.strip():
                payload: Any = json.loads(line)
                if isinstance(payload, dict):
                    rows.append(payload)
    return rows


def _read_s3_records(location: str, *, s3_client: Any | None) -> list[JsonDict]:
    parsed = urlparse(location)
    if parsed.scheme != "s3" or not parsed.netloc:
        raise ValueError(f"Invalid S3 dataset location: {location}")
    client = s3_client or _default_s3_client()
    bucket = parsed.netloc
    prefix = _normalize_s3_prefix(parsed.path.lstrip("/"))
    records: list[JsonDict] = []
    for key in _s3_data_keys(client, bucket=bucket, prefix=prefix):
        body = client.get_object(Bucket=bucket, Key=key)["Body"].read()
        if key.endswith(".parquet"):
            table = pq.read_table(BytesIO(body))  # type: ignore[no-untyped-call]
            records.extend(dict(record) for record in table.to_pylist())
        elif key.endswith(".jsonl"):
            records.extend(_jsonl_bytes_records(body))
    return records


def _s3_data_keys(client: Any, *, bucket: str, prefix: str) -> list[str]:
    keys: list[str] = []
    kwargs: dict[str, str] = {"Bucket": bucket, "Prefix": prefix}
    while True:
        response = client.list_objects_v2(**kwargs)
        for item in response.get("Contents", []):
            key = str(item.get("Key", ""))
            if key.endswith((".parquet", ".jsonl")):
                keys.append(key)
        if not response.get("IsTruncated"):
            break
        kwargs["ContinuationToken"] = str(response["NextContinuationToken"])
    return sorted(keys)


def _jsonl_bytes_records(body: bytes) -> list[JsonDict]:
    rows: list[JsonDict] = []
    for line in body.decode("utf-8").splitlines():
        if line.strip():
            payload: Any = json.loads(line)
            if isinstance(payload, dict):
                rows.append(payload)
    return rows


def _normalize_s3_prefix(prefix: str) -> str:
    if not prefix or prefix.endswith("/") or prefix.endswith((".parquet", ".jsonl")):
        return prefix
    return f"{prefix}/"


def _default_s3_client() -> Any:
    import boto3

    return boto3.client("s3")


def _jsonl_row_count(path: Path) -> int:
    count = 0
    with path.open(encoding="utf-8") as file:
        for line in file:
            if line.strip():
                json.loads(line)
                count += 1
    return count
