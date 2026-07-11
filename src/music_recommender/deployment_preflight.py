from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

from music_recommender.config import load_settings
from music_recommender.models import JsonDict
from music_recommender.storage.postgres import (
    PostgresDatabase,
    PostgresPoolSettings,
    PostgresStorageError,
)

_MIGRATION_VERSION = re.compile(r"^[0-9]{14}$")


class MigrationPreflightError(RuntimeError):
    pass


def expected_migration_versions(directory: Path) -> tuple[str, ...]:
    if not directory.is_dir():
        raise MigrationPreflightError("Supabase migrations directory was not found.")
    versions: list[str] = []
    for path in sorted(directory.glob("*.sql")):
        version = path.name.split("_", 1)[0]
        if not _MIGRATION_VERSION.fullmatch(version):
            raise MigrationPreflightError("Supabase migration filename is invalid.")
        versions.append(version)
    if not versions:
        raise MigrationPreflightError("No Supabase migrations were found.")
    if len(set(versions)) != len(versions):
        raise MigrationPreflightError("Supabase migration versions must be unique.")
    return tuple(versions)


def verify_migrations(connection: Any, *, expected: tuple[str, ...]) -> JsonDict:
    rows = connection.execute(
        "select version from supabase_migrations.schema_migrations order by version"
    ).fetchall()
    applied = {
        str(row["version"])
        for row in rows
        if isinstance(row, dict) and _MIGRATION_VERSION.fullmatch(str(row.get("version", "")))
    }
    missing = tuple(version for version in expected if version not in applied)
    if missing:
        raise MigrationPreflightError(f"Production database is missing {', '.join(missing)}.")
    return {
        "status": "ready",
        "expected_count": len(expected),
        "applied_count": len(applied),
        "latest_version": expected[-1],
    }


def main() -> int:
    try:
        expected = expected_migration_versions(Path("supabase/migrations"))
        settings = load_settings(require_spotify=False)
        database = PostgresDatabase(PostgresPoolSettings.from_settings(settings))
        try:
            with database.system_transaction() as connection:
                result = verify_migrations(connection, expected=expected)
        finally:
            database.close()
    except (MigrationPreflightError, PostgresStorageError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
