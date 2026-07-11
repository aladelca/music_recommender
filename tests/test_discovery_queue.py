from __future__ import annotations

import json
from typing import Any

import pytest

from music_recommender.product.discovery_queue import (
    DiscoveryQueueUnavailableError,
    SqsDiscoveryPublisher,
)


class FakeSqsClient:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[dict[str, Any]] = []

    def send_message(self, **kwargs: Any) -> dict[str, str]:
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("credential=do-not-expose")
        return {"MessageId": "message-1"}


def test_sqs_discovery_publisher_uses_fifo_deduplication_and_account_grouping() -> None:
    sqs = FakeSqsClient()
    publisher = SqsDiscoveryPublisher(
        queue_url="https://sqs.us-east-1.amazonaws.com/123/discovery.fifo",
        sqs_client=sqs,
    )

    publisher.publish(
        account_id="account-1",
        job_id="job-1",
        request_fingerprint="f" * 64,
    )

    call = sqs.calls[0]
    assert call["QueueUrl"].endswith("/discovery.fifo")
    assert call["MessageDeduplicationId"] == "job-1"
    assert call["MessageGroupId"] != "account-1"
    assert json.loads(call["MessageBody"]) == {
        "account_id": "account-1",
        "job_id": "job-1",
        "request_fingerprint": "f" * 64,
    }


def test_sqs_discovery_publisher_fails_closed_with_redacted_error() -> None:
    publisher = SqsDiscoveryPublisher(
        queue_url="https://sqs.us-east-1.amazonaws.com/123/discovery.fifo",
        sqs_client=FakeSqsClient(fail=True),
    )

    with pytest.raises(DiscoveryQueueUnavailableError) as error:
        publisher.publish(
            account_id="account-1",
            job_id="job-1",
            request_fingerprint="f" * 64,
        )

    assert "do-not-expose" not in str(error.value)


def test_sqs_discovery_publisher_requires_fifo_queue() -> None:
    with pytest.raises(ValueError, match="FIFO"):
        SqsDiscoveryPublisher(
            queue_url="https://sqs.us-east-1.amazonaws.com/123/discovery",
            sqs_client=FakeSqsClient(),
        )
