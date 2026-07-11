from __future__ import annotations

import json
from typing import Any

from music_recommender.api.discovery_worker_handler import run_discovery_batch
from music_recommender.observability import ProductObserver


class FakeWorker:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def run(self, *, account_id: str, job_id: str) -> object:
        self.calls.append((account_id, job_id))
        if job_id == "job-2":
            raise RuntimeError("upstream detail must not escape")
        return object()


def test_discovery_worker_handler_returns_only_failed_sqs_message_ids() -> None:
    worker = FakeWorker()
    observed: list[dict[str, Any]] = []
    observer = ProductObserver(
        service="discovery-worker",
        hash_key="observability-test-key-that-is-long-enough",
        emitter=observed.append,
    )
    event = {
        "Records": [
            sqs_record("message-1", "account-1", "job-1"),
            sqs_record("message-2", "account-1", "job-2"),
        ]
    }

    result = run_discovery_batch(
        event,
        worker=worker,
        observer=observer,
        now_milliseconds=lambda: 2_000,
    )

    assert result == {"batchItemFailures": [{"itemIdentifier": "message-2"}]}
    assert worker.calls == [("account-1", "job-1"), ("account-1", "job-2")]
    assert "upstream" not in json.dumps(result)
    assert len([event for event in observed if event["event"] == "discovery_message"]) == 2
    assert all("account-1" not in json.dumps(event) for event in observed)


def test_discovery_worker_handler_rejects_malformed_messages_without_processing() -> None:
    worker = FakeWorker()
    event = {
        "Records": [
            {
                "messageId": "message-bad",
                "eventSource": "aws:sqs",
                "body": json.dumps({"account_id": "account-1"}),
            }
        ]
    }

    result = run_discovery_batch(event, worker=worker)

    assert result == {"batchItemFailures": [{"itemIdentifier": "message-bad"}]}
    assert worker.calls == []


def sqs_record(message_id: str, account_id: str, job_id: str) -> dict[str, Any]:
    return {
        "messageId": message_id,
        "eventSource": "aws:sqs",
        "body": json.dumps(
            {
                "account_id": account_id,
                "job_id": job_id,
                "request_fingerprint": "f" * 64,
            }
        ),
        "attributes": {"SentTimestamp": "1000"},
    }
