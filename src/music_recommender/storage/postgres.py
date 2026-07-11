from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from psycopg import Error as PsycopgError
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool, PoolTimeout

from music_recommender.config import Settings


class PostgresStorageError(RuntimeError):
    """A redacted database failure safe to expose to application logs."""


class PostgresUnavailableError(PostgresStorageError):
    """The database pool could not establish a connection in time."""


@dataclass(frozen=True)
class PostgresPoolSettings:
    dsn: str = field(repr=False)
    min_size: int = 0
    max_size: int = 4
    acquire_timeout_seconds: float = 5.0
    statement_timeout_ms: int = 5_000

    @classmethod
    def from_settings(cls, settings: Settings) -> PostgresPoolSettings:
        if settings.supabase_db_url is None:
            raise ValueError("SUPABASE_DB_URL is required for Postgres storage.")
        return cls(
            dsn=settings.supabase_db_url,
            min_size=settings.postgres_pool_min_size,
            max_size=settings.postgres_pool_max_size,
            acquire_timeout_seconds=settings.postgres_pool_timeout_seconds,
            statement_timeout_ms=settings.postgres_statement_timeout_ms,
        )


class PostgresDatabase:
    def __init__(
        self,
        settings: PostgresPoolSettings,
        *,
        pool_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.settings = settings
        factory = pool_factory or ConnectionPool
        self._pool = factory(
            conninfo=settings.dsn,
            min_size=settings.min_size,
            max_size=settings.max_size,
            timeout=settings.acquire_timeout_seconds,
            kwargs={
                "application_name": "outside-the-loop",
                "options": f"-c statement_timeout={settings.statement_timeout_ms}",
                "prepare_threshold": None,
                "row_factory": dict_row,
            },
            open=False,
        )

    def open(self) -> None:
        if not self._pool.closed:
            return
        try:
            self._pool.open(wait=True, timeout=self.settings.acquire_timeout_seconds)
        except (PsycopgError, PoolTimeout):
            raise PostgresUnavailableError("Database connection unavailable.") from None

    def close(self) -> None:
        if self._pool.closed:
            return
        self._pool.close()

    @contextmanager
    def transaction(self, *, account_id: str) -> Iterator[Any]:
        normalized_account_id = account_id.strip()
        if not normalized_account_id:
            raise ValueError("account_id must not be empty.")
        with self.system_transaction() as connection:
            connection.execute(
                "select set_config('app.account_id', %s, true)",
                (normalized_account_id,),
            )
            yield connection

    @contextmanager
    def system_transaction(self) -> Iterator[Any]:
        self.open()
        try:
            with (
                self._pool.connection(timeout=self.settings.acquire_timeout_seconds) as connection,
                connection.transaction(),
            ):
                yield connection
        except PsycopgError:
            raise PostgresStorageError("Database operation failed.") from None
