from __future__ import annotations

from datetime import UTC, datetime

import pytest

from music_recommender.api.cleanup_handler import run_cleanup
from music_recommender.observability import ProductObserver
from music_recommender.storage.protocols import CleanupResult


class FakeCleanupRepository:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[datetime, int]] = []

    def cleanup(self, *, now: datetime, batch_size: int) -> CleanupResult:
        self.calls.append((now, batch_size))
        if self.fail:
            raise RuntimeError("database unavailable")
        return CleanupResult(
            oauth_states=1,
            application_sessions=2,
            source_cache_entries=3,
            candidate_edges=4,
            external_id_mappings=5,
            discovery_jobs=6,
            recommendation_sessions=7,
            removed_user_seeds=8,
            music_entities=9,
        )


def test_cleanup_handler_accepts_only_schedule_and_returns_safe_counts() -> None:
    now = datetime(2030, 1, 1, tzinfo=UTC)
    repository = FakeCleanupRepository()
    observed: list[dict[str, object]] = []

    result = run_cleanup(
        {"source": "aws.events", "detail-type": "Scheduled Event"},
        repository=repository,
        now=now,
        observer=ProductObserver(service="cleanup", emitter=observed.append),
    )

    assert result["status"] == "ok"
    assert result["deleted"]["music_entities"] == 9
    assert repository.calls == [(now, 1_000)]
    assert observed[0]["CleanupDeletedCount"] == 45


def test_cleanup_handler_raises_for_retry_on_database_failure() -> None:
    repository = FakeCleanupRepository(fail=True)

    with pytest.raises(RuntimeError, match="database unavailable"):
        run_cleanup(
            {"source": "aws.events", "detail-type": "Scheduled Event"},
            repository=repository,
            now=datetime(2030, 1, 1, tzinfo=UTC),
        )


def test_cleanup_handler_rejects_non_schedule_events() -> None:
    with pytest.raises(ValueError, match="Scheduled"):
        run_cleanup({}, repository=FakeCleanupRepository())
