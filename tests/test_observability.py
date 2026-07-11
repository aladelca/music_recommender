from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from music_recommender.api.observability_middleware import ProductObservabilityMiddleware
from music_recommender.observability import (
    ProductObserver,
    RecommendationCoverageObservation,
    mark_recommendation_coverage,
    mark_request_account,
    mark_request_error,
)


def test_shared_observer_has_no_web_framework_import_for_thin_workers() -> None:
    source = Path("src/music_recommender/observability.py").read_text()

    assert "from fastapi" not in source
    assert "from starlette" not in source


def test_observer_emits_emf_metrics_with_pseudonymous_user_correlation() -> None:
    events: list[dict[str, Any]] = []
    observer = ProductObserver(
        service="product-api",
        hash_key="observability-test-key-that-is-long-enough",
        emitter=events.append,
        epoch_milliseconds=lambda: 1_900_000_000_000,
    )

    observer.api_request(
        request_id="request-123",
        method="POST",
        route="/me/recommendations",
        status_code=201,
        latency_ms=42.25,
        account_id="spotify-account-private",
        error_code=None,
        recommendation=RecommendationCoverageObservation(
            status="ready",
            candidate_count=40,
            mapped_count=10,
            evidence_count=9,
            evidence_coverage=0.9,
        ),
    )

    assert len(events) == 1
    event = events[0]
    assert event["event"] == "api_request"
    assert event["request_id"] == "request-123"
    assert event["route"] == "/me/recommendations"
    assert event["user_correlation"] != "spotify-account-private"
    assert len(event["user_correlation"]) == 24
    assert event["recommendation_status"] == "ready"
    assert event["candidate_count"] == 40
    assert event["mapped_count"] == 10
    metric_names = {metric["Name"] for metric in event["_aws"]["CloudWatchMetrics"][0]["Metrics"]}
    assert {
        "RequestCount",
        "RequestLatencyMs",
        "RecommendationSourceCoveragePercent",
        "RecommendationEvidenceCoveragePercent",
    }.issubset(metric_names)
    assert event["_aws"]["Timestamp"] == 1_900_000_000_000
    assert "spotify-account-private" not in json.dumps(event)


def test_api_middleware_logs_only_bounded_metadata_and_returns_request_id() -> None:
    events: list[dict[str, Any]] = []
    observer = ProductObserver(
        service="product-api",
        hash_key="observability-test-key-that-is-long-enough",
        emitter=events.append,
    )
    app = FastAPI()
    app.add_middleware(ProductObservabilityMiddleware, observer=observer)

    @app.post("/items/{item_id}")
    def update_item(item_id: str, request: Request) -> dict[str, str]:
        del item_id
        mark_request_account(request, account_id="private-account")
        mark_request_error(request, error_code="spotify_reconnect_required")
        mark_recommendation_coverage(
            request,
            RecommendationCoverageObservation(
                status="degraded",
                candidate_count=12,
                mapped_count=8,
                evidence_count=7,
                evidence_coverage=0.875,
            ),
        )
        return {"status": "ok"}

    response = TestClient(app).post(
        "/items/item-with-private-value",
        json={"prompt": "a private listening prompt", "comment": "private comment"},
        headers={
            "Authorization": "Bearer private-token",
            "Cookie": "session=private-cookie",
            "X-Request-Id": "untrusted-private-request-id",
        },
    )

    assert response.status_code == 200
    assert response.headers["x-request-id"]
    assert response.headers["x-request-id"] != "untrusted-private-request-id"
    serialized = json.dumps(events)
    assert events[0]["route"] == "/items/{item_id}"
    assert events[0]["error_code"] == "spotify_reconnect_required"
    for private_value in (
        "item-with-private-value",
        "a private listening prompt",
        "private comment",
        "private-token",
        "private-cookie",
        "private-account",
        "untrusted-private-request-id",
    ):
        assert private_value not in serialized


def test_observer_emits_source_cache_queue_playlist_reconnect_and_cleanup_metrics() -> None:
    events: list[dict[str, Any]] = []
    observer = ProductObserver(
        service="discovery-worker",
        hash_key="observability-test-key-that-is-long-enough",
        emitter=events.append,
    )

    observer.cache_lookup(source="listenbrainz", hit=True, cache_status="fresh")
    observer.source_request(source="listenbrainz", status_class="success")
    observer.discovery_message(
        request_id="sqs-message-1",
        account_id="private-account",
        job_status="ready",
        source_status_class="success",
        queue_age_ms=1_250.0,
        latency_ms=850.0,
        succeeded=True,
    )
    observer.playlist_outcome(succeeded=False)
    observer.spotify_reconnect()
    observer.cleanup(deleted_count=18, latency_ms=25.0, succeeded=True)

    by_event = {event["event"]: event for event in events}
    assert by_event["cache_lookup"]["CacheHitCount"] == 1
    assert by_event["source_request"]["SourceRequestCount"] == 1
    assert by_event["discovery_message"]["QueueAgeMs"] == 1_250.0
    assert by_event["playlist_outcome"]["PlaylistExportFailureCount"] == 1
    assert by_event["spotify_reconnect"]["SpotifyReconnectCount"] == 1
    assert by_event["cleanup"]["CleanupDeletedCount"] == 18
    assert "private-account" not in json.dumps(events)


def test_observability_emitter_failure_does_not_fail_the_api_request() -> None:
    def fail_to_emit(payload: dict[str, Any]) -> None:
        del payload
        raise RuntimeError("logging transport unavailable")

    observer = ProductObserver(service="product-api", emitter=fail_to_emit)
    app = FastAPI()
    app.add_middleware(ProductObservabilityMiddleware, observer=observer)

    @app.get("/still-works")
    def still_works() -> dict[str, str]:
        return {"status": "ok"}

    response = TestClient(app).get("/still-works")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["x-request-id"]
