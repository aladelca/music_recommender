from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from music_recommender.api.app import create_app
from music_recommender.api.dependencies import (
    require_approved_mutating_user,
    require_approved_user,
)
from music_recommender.auth.models import ProductUser
from music_recommender.product.discovery_queue import DiscoveryQueueUnavailableError
from music_recommender.product.discovery_service import DiscoverySeedsRequiredError
from music_recommender.storage.protocols import DiscoveryJobRecord


class FakeDiscoveryJobService:
    def __init__(self, *, missing_seeds: bool = False, queue_unavailable: bool = False) -> None:
        self.missing_seeds = missing_seeds
        self.queue_unavailable = queue_unavailable
        self.enqueue_accounts: list[str] = []
        self.get_calls: list[tuple[str, str]] = []
        self.job = DiscoveryJobRecord(
            id="job-1",
            account_id="account-1",
            request_fingerprint="f" * 64,
            status="queued",
            source_adapters=(
                "listenbrainz_artist_radio",
                "listenbrainz_tag_radio",
            ),
            attempt_count=0,
            error_code=None,
            queued_at=datetime(2030, 1, 1, tzinfo=UTC),
            started_at=None,
            completed_at=None,
        )

    def enqueue(self, *, account_id: str) -> DiscoveryJobRecord:
        self.enqueue_accounts.append(account_id)
        if self.missing_seeds:
            raise DiscoverySeedsRequiredError("Select at least one seed.")
        if self.queue_unavailable:
            raise DiscoveryQueueUnavailableError("Automated discovery is unavailable.")
        return self.job

    def get(self, *, account_id: str, job_id: str) -> DiscoveryJobRecord | None:
        self.get_calls.append((account_id, job_id))
        if account_id == self.job.account_id and job_id == self.job.id:
            return self.job
        return None


def test_discovery_job_api_enqueues_and_reads_only_the_current_users_job() -> None:
    client, service = build_client()

    created = client.post("/discovery/jobs")
    fetched = client.get("/discovery/jobs/job-1")

    assert created.status_code == 202
    assert fetched.status_code == 200
    assert created.json() == fetched.json()
    assert created.json() == {
        "id": "job-1",
        "status": "queued",
        "source_adapters": [
            "listenbrainz_artist_radio",
            "listenbrainz_tag_radio",
        ],
        "attempt_count": 0,
        "error_code": None,
        "queued_at": "2030-01-01T00:00:00+00:00",
        "started_at": None,
        "completed_at": None,
    }
    assert service.enqueue_accounts == ["account-1"]
    assert service.get_calls == [("account-1", "job-1")]


def test_discovery_job_api_returns_not_found_for_unowned_or_unknown_job() -> None:
    client, _ = build_client()

    response = client.get("/discovery/jobs/another-job")

    assert response.status_code == 404
    assert response.json()["code"] == "discovery_job_not_found"


def test_discovery_job_api_requires_explicit_seeds() -> None:
    client, _ = build_client(missing_seeds=True)

    response = client.post("/discovery/jobs")

    assert response.status_code == 400
    assert response.json()["code"] == "discovery_seeds_required"


def test_discovery_job_api_reports_queue_outage_without_internal_details() -> None:
    client, _ = build_client(queue_unavailable=True)

    response = client.post("/discovery/jobs")

    assert response.status_code == 503
    assert response.json()["code"] == "discovery_queue_unavailable"


def build_client(
    *,
    missing_seeds: bool = False,
    queue_unavailable: bool = False,
) -> tuple[TestClient, FakeDiscoveryJobService]:
    service = FakeDiscoveryJobService(
        missing_seeds=missing_seeds,
        queue_unavailable=queue_unavailable,
    )
    app = create_app(load_env=False, discovery_job_service=service)
    user = ProductUser(
        account_id="account-1",
        display_name="Tester",
        access_status="approved",
        seed_ready=True,
        reauthorization_required=False,
    )
    app.dependency_overrides[require_approved_user] = lambda: user
    app.dependency_overrides[require_approved_mutating_user] = lambda: user
    return TestClient(app), service
