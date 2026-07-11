from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from music_recommender.product.source_audit import audit_source_inventory


class FakeResult:
    def __init__(self, row: dict[str, int]) -> None:
        self.row = row

    def fetchone(self) -> dict[str, int]:
        return self.row


class FakeConnection:
    def __init__(self, row: dict[str, int]) -> None:
        self.row = row
        self.params: tuple[datetime, ...] | None = None

    def execute(self, query: str, params: tuple[datetime, ...]) -> FakeResult:
        assert "candidate_edges" in query
        assert "external_id_mappings" in query
        self.params = params
        return FakeResult(self.row)


class FakeDatabase:
    def __init__(self, row: dict[str, int]) -> None:
        self.connection = FakeConnection(row)

    @contextmanager
    def system_transaction(self) -> Iterator[FakeConnection]:
        yield self.connection


def test_source_inventory_audit_reports_only_aggregate_coverage() -> None:
    now = datetime(2030, 1, 1, tzinfo=UTC)
    database = FakeDatabase(
        {
            "fresh_candidate_count": 20,
            "stale_candidate_count": 2,
            "fresh_spotify_mapping_count": 10,
            "evidenced_mapping_count": 9,
        }
    )

    audit = audit_source_inventory(database, now=now)

    assert audit.to_dict() == {
        "status": "ready",
        "fresh_candidate_count": 20,
        "fresh_spotify_mapping_count": 10,
        "evidenced_mapping_count": 9,
        "stale_candidate_count": 2,
        "evidence_coverage": 0.9,
        "limitations": [],
    }
    assert database.connection.params == (now,) * 6
