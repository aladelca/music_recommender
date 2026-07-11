from __future__ import annotations

import os

import pytest

from music_recommender.storage.postgres import PostgresDatabase, PostgresPoolSettings


def test_postgres_database_connects_and_scopes_account_transaction() -> None:
    database_url = os.getenv("TEST_SUPABASE_DB_URL")
    if database_url is None:
        pytest.skip("Set TEST_SUPABASE_DB_URL to run the local Supabase connection test.")

    database = PostgresDatabase(PostgresPoolSettings(dsn=database_url))
    try:
        with database.transaction(account_id="integration-account") as connection:
            row = connection.execute(
                "select current_setting('app.account_id', true) as account_id"
            ).fetchone()
    finally:
        database.close()

    assert row == {"account_id": "integration-account"}
