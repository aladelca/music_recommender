from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import pyarrow.parquet as pq

JsonReadyDict = dict[str, object]

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


def _jsonl_row_count(path: Path) -> int:
    count = 0
    with path.open(encoding="utf-8") as file:
        for line in file:
            if line.strip():
                json.loads(line)
                count += 1
    return count
