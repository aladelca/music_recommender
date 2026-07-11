from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from music_recommender.config import load_settings
from music_recommender.models import JsonDict
from music_recommender.observability import ProductObserver, SourceStatusClass
from music_recommender.product.discovery_service import DiscoveryRetryableError, DiscoveryWorker
from music_recommender.sources.listenbrainz_api import ListenBrainzApiClient
from music_recommender.storage.postgres import PostgresDatabase, PostgresPoolSettings
from music_recommender.storage.postgres_repositories import PostgresRepositories


class DiscoveryBatchWorker(Protocol):
    def run(self, *, account_id: str, job_id: str) -> object: ...


@dataclass(frozen=True)
class DiscoveryWorkerRuntime:
    worker: DiscoveryWorker
    database: PostgresDatabase
    listenbrainz: ListenBrainzApiClient
    observer: ProductObserver

    def close(self) -> None:
        self.listenbrainz.close()
        self.database.close()


def handler(event: JsonDict, _context: Any) -> JsonDict:
    runtime = build_discovery_worker_runtime()
    try:
        return run_discovery_batch(event, worker=runtime.worker, observer=runtime.observer)
    finally:
        runtime.close()


def build_discovery_worker_runtime() -> DiscoveryWorkerRuntime:
    settings = load_settings(require_spotify=False)
    if settings.musicbrainz_contact_email is None:
        raise ValueError("MUSICBRAINZ_CONTACT_EMAIL is required for automated discovery.")
    database = PostgresDatabase(PostgresPoolSettings.from_settings(settings))
    repositories = PostgresRepositories(database)
    if settings.observability_hash_key is None:
        raise ValueError("OBSERVABILITY_HASH_KEY is required for the discovery worker.")
    observer = ProductObserver(
        service="discovery-worker",
        hash_key=settings.observability_hash_key,
    )
    listenbrainz = ListenBrainzApiClient(
        contact_email=settings.musicbrainz_contact_email,
        app_version="0.1.0",
    )
    return DiscoveryWorkerRuntime(
        worker=DiscoveryWorker(
            jobs=repositories.discovery_jobs,
            seeds=repositories.seeds,
            entities=repositories.music_entities,
            cache=repositories.source_cache,
            candidate_edges=repositories.candidate_edges,
            rate_limiter=repositories.source_rate_limits,
            listenbrainz=listenbrainz,
            observer=observer,
        ),
        database=database,
        listenbrainz=listenbrainz,
        observer=observer,
    )


def run_discovery_batch(
    event: JsonDict,
    *,
    worker: DiscoveryBatchWorker,
    observer: ProductObserver | None = None,
    now_milliseconds: Callable[[], int] | None = None,
) -> JsonDict:
    records = event.get("Records")
    if not isinstance(records, list):
        raise ValueError("Expected an SQS records event.")
    failures: list[JsonDict] = []
    resolved_now_milliseconds = now_milliseconds or (lambda: time.time_ns() // 1_000_000)
    for value in records:
        message_id = _message_id(value)
        started = time.perf_counter()
        account_id: str | None = None
        try:
            account_id, job_id = _message(value)
            result = worker.run(account_id=account_id, job_id=job_id)
            if observer is not None and message_id is not None:
                status = _job_status(result)
                observer.discovery_message(
                    request_id=message_id,
                    account_id=account_id,
                    job_status=status,
                    source_status_class=_source_status_class(status),
                    queue_age_ms=_queue_age_ms(value, now_milliseconds=resolved_now_milliseconds),
                    latency_ms=(time.perf_counter() - started) * 1_000,
                    succeeded=status not in {"failed", "error"},
                )
        except Exception as error:
            if message_id is None:
                raise ValueError("SQS record is missing a message identifier.") from None
            if observer is not None and account_id is not None:
                observer.discovery_message(
                    request_id=message_id,
                    account_id=account_id,
                    job_status="failed",
                    source_status_class=(
                        "transient_failure"
                        if isinstance(error, DiscoveryRetryableError)
                        else "permanent_failure"
                    ),
                    queue_age_ms=_queue_age_ms(value, now_milliseconds=resolved_now_milliseconds),
                    latency_ms=(time.perf_counter() - started) * 1_000,
                    succeeded=False,
                )
            failures.append({"itemIdentifier": message_id})
    return {"batchItemFailures": failures}


def _message(value: Any) -> tuple[str, str]:
    if not isinstance(value, dict) or value.get("eventSource") != "aws:sqs":
        raise ValueError("Expected an SQS record.")
    body = value.get("body")
    if not isinstance(body, str) or len(body) > 2_048:
        raise ValueError("SQS discovery message body is invalid.")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise ValueError("SQS discovery message body is invalid.") from None
    if not isinstance(payload, dict):
        raise ValueError("SQS discovery message body is invalid.")
    account_id = _message_text(payload.get("account_id"), limit=255)
    job_id = _message_text(payload.get("job_id"), limit=100)
    fingerprint = payload.get("request_fingerprint")
    if (
        not isinstance(fingerprint, str)
        or len(fingerprint) != 64
        or any(character not in "0123456789abcdef" for character in fingerprint)
    ):
        raise ValueError("SQS discovery fingerprint is invalid.")
    return account_id, job_id


def _message_id(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    message_id = value.get("messageId")
    if not isinstance(message_id, str) or not 1 <= len(message_id) <= 100:
        return None
    return message_id


def _message_text(value: Any, *, limit: int) -> str:
    if not isinstance(value, str):
        raise ValueError("SQS discovery message is invalid.")
    normalized = value.strip()
    if (
        not normalized
        or len(normalized) > limit
        or any(ord(character) < 32 for character in normalized)
    ):
        raise ValueError("SQS discovery message is invalid.")
    return normalized


def _job_status(result: object) -> str:
    value = getattr(result, "status", None)
    if isinstance(value, str) and value in {
        "queued",
        "running",
        "ready",
        "degraded",
        "failed",
    }:
        return value
    return "processed"


def _source_status_class(status: str) -> SourceStatusClass:
    if status in {"ready", "processed"}:
        return "success"
    if status in {"queued", "running", "degraded"}:
        return "degraded"
    return "permanent_failure"


def _queue_age_ms(value: Any, *, now_milliseconds: Callable[[], int]) -> float:
    if not isinstance(value, dict):
        return 0.0
    attributes = value.get("attributes")
    if not isinstance(attributes, dict):
        return 0.0
    sent_timestamp = attributes.get("SentTimestamp")
    if not isinstance(sent_timestamp, str) or not sent_timestamp.isdigit():
        return 0.0
    return float(max(now_milliseconds() - int(sent_timestamp), 0))
