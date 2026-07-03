from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from music_recommender.api.app import create_app
from music_recommender.recommender.feedback import FeedbackService, JsonFeedbackStore


def test_feedback_endpoint_records_event() -> None:
    service = FakeApiService()
    client = TestClient(create_app(service=service))

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


class FakeApiService:
    def __init__(self) -> None:
        self.feedback_request: dict[str, Any] | None = None

    def record_feedback(self, request: Any) -> dict[str, Any]:
        self.feedback_request = request.model_dump()
        return {
            "event_id": "feedback-1",
            "status": "recorded",
        }
