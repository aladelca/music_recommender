from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from music_recommender.api.app import create_app


def test_health_reports_config_presence_without_secret_values(
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
    assert body["config"] == {
        "aws_region": "us-east-1",
        "api_key_required": False,
        "aws_secrets_prefix_present": True,
        "music_recommender_bucket_present": True,
        "openai_api_key_present": True,
        "recommender_data_mode": "s3",
        "recommender_data_root_present": True,
        "spotify_client_id_present": True,
        "spotify_client_secret_present": True,
        "spotify_user_refresh_token_present": True,
    }
    assert "sk-test-secret" not in response.text
    assert "spotify-secret" not in response.text
    assert "spotify-refresh" not in response.text


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
