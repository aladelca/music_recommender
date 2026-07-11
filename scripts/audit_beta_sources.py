#!/usr/bin/env python3
from __future__ import annotations

import json

from music_recommender.config import load_settings
from music_recommender.product.source_audit import audit_source_inventory
from music_recommender.storage.postgres import PostgresDatabase, PostgresPoolSettings


def main() -> int:
    settings = load_settings()
    database = PostgresDatabase(PostgresPoolSettings.from_settings(settings))
    try:
        audit = audit_source_inventory(database)
    finally:
        database.close()
    print(json.dumps(audit.to_dict(), sort_keys=True))
    return 0 if audit.status == "ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())
