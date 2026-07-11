from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi.testclient import TestClient

from music_recommender.api.app import create_app
from music_recommender.api.dependencies import (
    require_approved_mutating_user,
    require_approved_user,
)
from music_recommender.auth.models import ProductUser
from music_recommender.product.feedback_service import ProductFeedbackResult
from music_recommender.storage.protocols import FeedbackEventRecord, SessionEvaluationRecord

SESSION_ID = "40000000-0000-0000-0000-000000000001"
RECORDING = "30000000-0000-0000-0000-000000000001"


class FakeFeedbackEvaluationService:
    def __init__(self) -> None:
        self.feedback_calls: list[dict[str, Any]] = []
        self.evaluation_calls: list[dict[str, Any]] = []

    def record_feedback(self, **kwargs: Any) -> ProductFeedbackResult:
        self.feedback_calls.append(kwargs)
        return ProductFeedbackResult(event=feedback_event(), idempotent_replay=False)

    def save_evaluation(self, **kwargs: Any) -> SessionEvaluationRecord:
        self.evaluation_calls.append(kwargs)
        return evaluation()

    def get_evaluation(self, **kwargs: Any) -> SessionEvaluationRecord:
        assert kwargs == {"account_id": "account-1", "session_id": SESSION_ID}
        return evaluation()


def test_product_feedback_and_evaluation_derive_current_account() -> None:
    client, service = build_client()

    feedback_response = client.post(
        f"/me/recommendations/{SESSION_ID}/feedback",
        json={
            "recording_mbid": RECORDING,
            "event_type": "dislike",
            "reason": "Not for me",
        },
        headers={"Idempotency-Key": "feedback-key-1"},
    )
    evaluation_response = client.put(
        f"/me/recommendations/{SESSION_ID}/evaluation",
        json={
            "comparison": "better",
            "explanation_usefulness": 5,
            "novelty_quality": 4,
            "comment": "Useful evidence.",
        },
    )
    fetched = client.get(f"/me/recommendations/{SESSION_ID}/evaluation")

    assert feedback_response.status_code == 201
    assert feedback_response.json()["event_type"] == "dislike"
    assert evaluation_response.status_code == 200
    assert fetched.json() == evaluation_response.json()
    assert service.feedback_calls[0]["account_id"] == "account-1"
    assert service.feedback_calls[0]["idempotency_key"] == "feedback-key-1"
    assert service.evaluation_calls[0]["account_id"] == "account-1"


def test_product_feedback_contract_rejects_generic_metadata_and_missing_idempotency() -> None:
    client, service = build_client()

    response = client.post(
        f"/me/recommendations/{SESSION_ID}/feedback",
        json={
            "recording_mbid": RECORDING,
            "event_type": "like",
            "metadata": {"account": "another-user", "raw_prompt": "sensitive"},
        },
    )

    assert response.status_code == 422
    assert service.feedback_calls == []


def build_client() -> tuple[TestClient, FakeFeedbackEvaluationService]:
    service = FakeFeedbackEvaluationService()
    app = create_app(load_env=False, feedback_evaluation_service=service)
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


def feedback_event() -> FeedbackEventRecord:
    now = datetime(2030, 1, 1, tzinfo=UTC)
    return FeedbackEventRecord(
        id="60000000-0000-0000-0000-000000000001",
        account_id="account-1",
        session_id=SESSION_ID,
        recording_mbid=RECORDING,
        event_type="dislike",
        metadata={"reason": "Not for me"},
        idempotency_key="feedback-key-1",
        created_at=now,
    )


def evaluation() -> SessionEvaluationRecord:
    now = datetime(2030, 1, 1, tzinfo=UTC)
    return SessionEvaluationRecord(
        session_id=SESSION_ID,
        account_id="account-1",
        comparison="better",
        explanation_usefulness=5,
        novelty_quality=4,
        comment="Useful evidence.",
        created_at=now,
        updated_at=now,
    )
