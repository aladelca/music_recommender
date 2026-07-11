from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from music_recommender.deployment_preflight import (
    MigrationPreflightError,
    expected_migration_versions,
    verify_migrations,
)


class FakeConnection:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def execute(self, query: str) -> FakeConnection:
        assert "supabase_migrations.schema_migrations" in query
        return self

    def fetchall(self) -> list[dict[str, Any]]:
        return self.rows


def test_migration_preflight_compares_local_versions_without_exposing_database_values(
    tmp_path: Path,
) -> None:
    (tmp_path / "20260710160000_core.sql").write_text("select 1;\n")
    (tmp_path / "20260710170000_status.sql").write_text("select 1;\n")
    expected = expected_migration_versions(tmp_path)

    result = verify_migrations(
        FakeConnection([{"version": version} for version in expected]),
        expected=expected,
    )

    assert result == {
        "status": "ready",
        "expected_count": 2,
        "applied_count": 2,
        "latest_version": "20260710170000",
    }


def test_migration_preflight_fails_closed_when_production_is_behind() -> None:
    with pytest.raises(MigrationPreflightError, match="missing 20260710170000"):
        verify_migrations(
            FakeConnection([{"version": "20260710160000"}]),
            expected=("20260710160000", "20260710170000"),
        )
