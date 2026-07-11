from __future__ import annotations

import hashlib
import json
from typing import Any, Protocol
from urllib.parse import urlparse


class DiscoveryQueueUnavailableError(RuntimeError):
    pass


class SqsClient(Protocol):
    def send_message(self, **kwargs: Any) -> Any: ...


class SqsDiscoveryPublisher:
    def __init__(self, *, queue_url: str, sqs_client: SqsClient) -> None:
        normalized_url = queue_url.strip()
        parsed = urlparse(normalized_url)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or not parsed.path.endswith(".fifo")
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Discovery queue must be a valid HTTPS FIFO SQS URL.")
        self.queue_url = normalized_url
        self.sqs_client = sqs_client

    def publish(
        self,
        *,
        account_id: str,
        job_id: str,
        request_fingerprint: str,
    ) -> None:
        normalized_account_id = _bounded_text(account_id, name="account_id", limit=255)
        normalized_job_id = _bounded_text(job_id, name="job_id", limit=100)
        normalized_fingerprint = request_fingerprint.strip().lower()
        if len(normalized_fingerprint) != 64 or any(
            character not in "0123456789abcdef" for character in normalized_fingerprint
        ):
            raise ValueError("request_fingerprint must be a SHA-256 digest.")
        message = {
            "account_id": normalized_account_id,
            "job_id": normalized_job_id,
            "request_fingerprint": normalized_fingerprint,
        }
        try:
            self.sqs_client.send_message(
                QueueUrl=self.queue_url,
                MessageBody=json.dumps(message, sort_keys=True, separators=(",", ":")),
                MessageGroupId=hashlib.sha256(normalized_account_id.encode("utf-8")).hexdigest(),
                MessageDeduplicationId=normalized_job_id,
            )
        except Exception:
            raise DiscoveryQueueUnavailableError(
                "Automated discovery queue is temporarily unavailable."
            ) from None


def _bounded_text(value: str, *, name: str, limit: int) -> str:
    normalized = value.strip()
    if (
        not normalized
        or len(normalized) > limit
        or any(ord(character) < 32 for character in normalized)
    ):
        raise ValueError(f"{name} is invalid.")
    return normalized
