from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from music_recommender.api.app import create_app


def test_health_is_shallow_and_does_not_report_config_inventory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-secret")
    monkeypatch.setenv("SPOTIFY_APP_CLIENT_ID", "spotify-client")
    monkeypatch.setenv("SPOTIFY_APP_CLIENT_SECRET", "spotify-secret")
    monkeypatch.setenv("SPOTIFY_USER_REFRESH_TOKEN", "spotify-refresh")
    monkeypatch.setenv("MUSIC_RECOMMENDER_BUCKET", "music-recommender-demo")
    monkeypatch.setenv("AWS_SECRETS_PREFIX", "music-recommender/demo/")
    monkeypatch.setenv("RECOMMENDER_DATA_MODE", "s3")
    monkeypatch.setenv("RECOMMENDER_DATA_ROOT", "s3://music-recommender-demo/gold")

    response = TestClient(create_app(load_env=False)).get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == "0.1.0"
    assert set(body) == {"status", "version"}
    assert "sk-test-secret" not in response.text
    assert "spotify-secret" not in response.text
    assert "spotify-refresh" not in response.text


def test_readiness_probe_returns_only_ready_or_unavailable() -> None:
    ready_client = TestClient(create_app(load_env=False, readiness_probe=lambda: True))
    unavailable_client = TestClient(create_app(load_env=False, readiness_probe=lambda: False))

    assert ready_client.get("/ready").json() == {"status": "ready"}
    unavailable = unavailable_client.get("/ready")
    assert unavailable.status_code == 503
    assert unavailable.json() == {"status": "unavailable"}


def test_configured_api_key_is_required_for_non_health_routes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RECOMMENDER_API_KEY", "demo-secret")
    client = TestClient(create_app(load_env=False, service=FakeApiService()))

    assert client.get("/health").status_code == 200
    unauthorized_response = client.post(
        "/feedback",
        json={"session_id": "s", "track_id": "t", "event_type": "like"},
    )
    assert unauthorized_response.status_code == 401

    response = client.post(
        "/feedback",
        headers={"X-API-Key": "demo-secret"},
        json={"session_id": "s", "track_id": "t", "event_type": "like"},
    )

    assert response.status_code == 200
    assert response.json() == {"event_id": "feedback-1", "status": "recorded"}


class FakeApiService:
    def record_feedback(self, request: object) -> dict[str, str]:
        return {"event_id": "feedback-1", "status": "recorded"}
