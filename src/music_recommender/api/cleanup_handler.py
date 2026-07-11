from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from music_recommender.config import load_settings
from music_recommender.models import JsonDict
from music_recommender.observability import ProductObserver
from music_recommender.storage.postgres import PostgresDatabase, PostgresPoolSettings
from music_recommender.storage.postgres_repositories import PostgresCleanupRepository
from music_recommender.storage.protocols import CleanupRepository


def handler(event: JsonDict, _context: Any) -> JsonDict:
    settings = load_settings(require_spotify=False)
    database = PostgresDatabase(PostgresPoolSettings.from_settings(settings))
    observer = ProductObserver(service="cleanup")
    try:
        return run_cleanup(
            event,
            repository=PostgresCleanupRepository(database),
            observer=observer,
        )
    finally:
        database.close()


def run_cleanup(
    event: JsonDict,
    *,
    repository: CleanupRepository,
    now: datetime | None = None,
    observer: ProductObserver | None = None,
    monotonic: Callable[[], float] = time.perf_counter,
) -> JsonDict:
    if event.get("source") != "aws.events" or event.get("detail-type") != "Scheduled Event":
        raise ValueError("Expected an EventBridge Scheduled Event.")
    started = monotonic()
    try:
        result = repository.cleanup(
            now=_aware_utc(now or datetime.now(UTC)),
            batch_size=1_000,
        )
    except Exception:
        if observer is not None:
            observer.cleanup(
                deleted_count=0,
                latency_ms=(monotonic() - started) * 1_000,
                succeeded=False,
            )
        raise
    if observer is not None:
        observer.cleanup(
            deleted_count=sum(result.to_dict().values()),
            latency_ms=(monotonic() - started) * 1_000,
            succeeded=True,
        )
    return {"status": "ok", "deleted": result.to_dict()}


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Cleanup timestamps must be timezone-aware.")
    return value.astimezone(UTC)
