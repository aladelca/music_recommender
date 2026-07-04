from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from music_recommender.api.app import create_app
from music_recommender.api.services import DemoApiService
from music_recommender.recommender.feedback import FeedbackService, JsonFeedbackStore
from music_recommender.recommender.sessions import (
    JsonRecommendationSessionStore,
    RecommendationSession,
)


def test_feedback_endpoint_records_event() -> None:
    service = FakeApiService()
    client = TestClient(create_app(load_env=False, service=service))

    response = client.post(
        "/feedback",
        json={
            "session_id": "session-1",
            "track_id": "sunny",
            "event_type": "like",
            "metadata": {"reason": "demo"},
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "recorded"
    assert body["event_id"] == "feedback-1"
    assert service.feedback_request == {
        "session_id": "session-1",
        "track_id": "sunny",
        "event_type": "like",
        "metadata": {"reason": "demo"},
    }


def test_feedback_service_persists_local_json(tmp_path: Path) -> None:
    service = FeedbackService(store=JsonFeedbackStore(tmp_path / "feedback.json"))

    event = service.record_feedback(
        session_id="session-1",
        track_id="sunny",
        event_type="like",
        metadata={"reason": "demo"},
    )

    events = service.list_feedback("session-1")
    assert event.event_id
    assert len(events) == 1
    assert events[0].track_id == "sunny"
    assert events[0].metadata == {"reason": "demo"}


def test_demo_api_service_rejects_feedback_for_unknown_session(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setenv("RECOMMENDER_SESSION_STORE_PATH", str(tmp_path / "sessions.json"))
    monkeypatch.setenv("RECOMMENDER_FEEDBACK_STORE_PATH", str(tmp_path / "feedback.json"))
    client = TestClient(create_app(load_env=False, service=DemoApiService()))

    response = client.post(
        "/feedback",
        json={
            "session_id": "missing",
            "track_id": "sunny",
            "event_type": "like",
        },
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Recommendation session not found: missing"}


def test_demo_api_service_rejects_feedback_for_track_outside_session(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    session_path = tmp_path / "sessions.json"
    JsonRecommendationSessionStore(session_path).put(build_session())
    monkeypatch.setenv("RECOMMENDER_SESSION_STORE_PATH", str(session_path))
    monkeypatch.setenv("RECOMMENDER_FEEDBACK_STORE_PATH", str(tmp_path / "feedback.json"))
    client = TestClient(create_app(load_env=False, service=DemoApiService()))

    response = client.post(
        "/feedback",
        json={
            "session_id": "session-1",
            "track_id": "invented",
            "event_type": "like",
        },
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": "Track IDs were not recommended for this session: invented"
    }


def test_demo_api_service_records_feedback_for_session_track(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    session_path = tmp_path / "sessions.json"
    feedback_path = tmp_path / "feedback.json"
    JsonRecommendationSessionStore(session_path).put(build_session())
    monkeypatch.setenv("RECOMMENDER_SESSION_STORE_PATH", str(session_path))
    monkeypatch.setenv("RECOMMENDER_FEEDBACK_STORE_PATH", str(feedback_path))
    client = TestClient(create_app(load_env=False, service=DemoApiService()))

    response = client.post(
        "/feedback",
        json={
            "session_id": "session-1",
            "track_id": "sunny",
            "event_type": "like",
            "metadata": {"reason": "demo"},
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "recorded"
    events = JsonFeedbackStore(feedback_path).list_by_session("session-1")
    assert len(events) == 1
    assert events[0].track_id == "sunny"
    assert events[0].metadata == {"reason": "demo"}


class FakeApiService:
    def __init__(self) -> None:
        self.feedback_request: dict[str, Any] | None = None

    def record_feedback(self, request: Any) -> dict[str, Any]:
        self.feedback_request = request.model_dump()
        return {
            "event_id": "feedback-1",
            "status": "recorded",
        }


def build_session() -> RecommendationSession:
    return RecommendationSession(
        session_id="session-1",
        user_id="12175364859",
        prompt="cheer me up",
        intent={"label": "cheer-up"},
        recommended_track_ids=("sunny", "dance"),
        recommendations=(
            {"track": {"id": "sunny", "name": "Sunny Recovery"}, "score": {"total": 0.9}},
            {"track": {"id": "dance", "name": "Dance Again"}, "score": {"total": 0.8}},
        ),
        catalog_run_id="catalog-run",
        interaction_run_id=None,
        playlist_candidate={"track_ids": ["sunny", "dance"]},
        created_at="2026-07-04T00:00:00+00:00",
        updated_at="2026-07-04T00:00:00+00:00",
    )
