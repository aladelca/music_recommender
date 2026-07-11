from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from psycopg.rows import dict_row

from music_recommender.storage.postgres import PostgresDatabase, PostgresPoolSettings


class FakeTransaction:
    def __enter__(self) -> FakeTransaction:
        return self

    def __exit__(self, *_args: object) -> None:
        return None


class FakeConnection:
    def __init__(self) -> None:
        self.executions: list[tuple[str, tuple[object, ...]]] = []
        self.transaction_count = 0

    def transaction(self) -> FakeTransaction:
        self.transaction_count += 1
        return FakeTransaction()

    def execute(self, query: str, params: tuple[object, ...]) -> None:
        self.executions.append((query, params))


class FakePool:
    def __init__(self, connection: FakeConnection) -> None:
        self.closed = True
        self.connection_value = connection
        self.open_calls: list[tuple[bool, float | None]] = []
        self.connection_timeouts: list[float | None] = []
        self.close_calls = 0

    def open(self, *, wait: bool, timeout: float | None = None) -> None:
        self.open_calls.append((wait, timeout))
        self.closed = False

    @contextmanager
    def connection(self, timeout: float | None = None) -> Iterator[FakeConnection]:
        self.connection_timeouts.append(timeout)
        yield self.connection_value

    def close(self) -> None:
        self.close_calls += 1
        self.closed = True


def test_postgres_pool_settings_do_not_reveal_database_url() -> None:
    settings = PostgresPoolSettings(
        dsn="postgresql://backend:super-secret@db.example.test/postgres?sslmode=require"
    )

    assert "super-secret" not in repr(settings)


def test_postgres_database_opens_lazily_and_sets_account_context() -> None:
    captured: dict[str, Any] = {}
    connection = FakeConnection()
    pool = FakePool(connection)

    def pool_factory(**kwargs: Any) -> FakePool:
        captured.update(kwargs)
        return pool

    database = PostgresDatabase(
        PostgresPoolSettings(
            dsn="postgresql://backend:secret@127.0.0.1:55432/postgres",
            min_size=0,
            max_size=3,
            acquire_timeout_seconds=2.5,
            statement_timeout_ms=4_000,
        ),
        pool_factory=pool_factory,
    )

    assert pool.open_calls == []
    assert captured == {
        "conninfo": "postgresql://backend:secret@127.0.0.1:55432/postgres",
        "min_size": 0,
        "max_size": 3,
        "timeout": 2.5,
        "kwargs": {
            "application_name": "outside-the-loop",
            "options": "-c statement_timeout=4000",
            "prepare_threshold": None,
            "row_factory": dict_row,
        },
        "open": False,
    }

    with database.transaction(account_id="spotify-account") as transaction_connection:
        assert transaction_connection is connection

    assert pool.open_calls == [(True, 2.5)]
    assert pool.connection_timeouts == [2.5]
    assert connection.transaction_count == 1
    assert connection.executions == [
        (
            "select set_config('app.account_id', %s, true)",
            ("spotify-account",),
        )
    ]

    database.close()
    assert pool.close_calls == 1


def test_postgres_system_transaction_does_not_set_account_context() -> None:
    connection = FakeConnection()
    pool = FakePool(connection)
    database = PostgresDatabase(
        PostgresPoolSettings(dsn="postgresql://backend:secret@127.0.0.1/postgres"),
        pool_factory=lambda **_kwargs: pool,
    )

    with database.system_transaction() as transaction_connection:
        assert transaction_connection is connection

    assert connection.executions == []
    assert connection.transaction_count == 1


def test_postgres_transaction_rejects_empty_account_id() -> None:
    connection = FakeConnection()
    pool = FakePool(connection)
    database = PostgresDatabase(
        PostgresPoolSettings(dsn="postgresql://backend:secret@127.0.0.1/postgres"),
        pool_factory=lambda **_kwargs: pool,
    )

    with (
        pytest.raises(ValueError, match="account_id must not be empty"),
        database.transaction(account_id=" "),
    ):
        pass

    assert pool.open_calls == []
