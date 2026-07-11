from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from fastapi.testclient import TestClient

from music_recommender.api.app import create_app
from music_recommender.api.dependencies import (
    require_approved_mutating_user,
    require_approved_user,
)
from music_recommender.auth.models import ProductUser
from music_recommender.product.recommendation_service import (
    RecommendationHistoryPage,
    RecommendationNotFoundError,
)
from music_recommender.storage.protocols import (
    RecommendationItemRecord,
    RecommendationSessionBundle,
    RecommendationSessionRecord,
)

SESSION_ID = "40000000-0000-0000-0000-000000000001"
SEED_ID = "00000000-0000-0000-0000-000000000001"
RECORDING_MBID = "30000000-0000-0000-0000-000000000001"


class FakeRecommendationService:
    def __init__(self) -> None:
        self.bundle = recommendation_bundle()
        self.generate_calls: list[dict[str, Any]] = []
        self.review_calls: list[dict[str, Any]] = []

    def generate(self, **kwargs: Any) -> RecommendationSessionBundle:
        self.generate_calls.append(kwargs)
        return self.bundle

    def get(self, *, account_id: str, session_id: str) -> RecommendationSessionBundle:
        if account_id != "account-1" or session_id != SESSION_ID:
            raise RecommendationNotFoundError("Recommendation session was not found.")
        return self.bundle

    def history(self, **kwargs: Any) -> RecommendationHistoryPage:
        assert kwargs["account_id"] == "account-1"
        return RecommendationHistoryPage(sessions=(self.bundle.session,), next_cursor=None)

    def review(self, **kwargs: Any) -> RecommendationSessionBundle:
        self.review_calls.append(kwargs)
        return replace(
            self.bundle,
            session=replace(
                self.bundle.session,
                status="reviewed",
                reviewed_playlist_name=kwargs["playlist_name"],
                reviewed_playlist_public=kwargs["playlist_public"],
            ),
        )


def test_product_recommendation_routes_derive_account_and_hide_internal_scores() -> None:
    client, service = build_client()
    request = {
        "prompt": "Late night trip hop",
        "adventure": "balanced",
        "allow_explicit": False,
        "seed_ids": [SEED_ID],
    }

    created = client.post("/me/recommendations", json=request)
    fetched = client.get(f"/me/recommendations/{SESSION_ID}")
    history = client.get("/me/recommendations", params={"limit": 10})

    assert created.status_code == 201
    assert fetched.status_code == 200
    assert created.json() == fetched.json()
    assert created.json()["recommendations"][0]["evidence"]["verifiable"] is True
    assert "internal_score_components" not in created.text
    assert history.status_code == 200
    assert history.json()["sessions"][0]["id"] == SESSION_ID
    assert service.generate_calls == [
        {
            "account_id": "account-1",
            "prompt": "Late night trip hop",
            "adventure": "balanced",
            "allow_explicit": False,
            "seed_ids": (SEED_ID,),
        }
    ]


def test_product_recommendation_review_requires_explicit_name_order_and_visibility() -> None:
    client, service = build_client()

    response = client.put(
        f"/me/recommendations/{SESSION_ID}/selection",
        json={
            "recording_mbids": [RECORDING_MBID],
            "playlist_name": "Late Night Finds",
            "public": True,
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "reviewed"
    assert response.json()["review"] == {
        "playlist_name": "Late Night Finds",
        "public": True,
    }
    assert service.review_calls[0]["account_id"] == "account-1"
    assert service.review_calls[0]["recording_mbids"] == (RECORDING_MBID,)


def test_product_recommendation_contract_rejects_legacy_side_effect_and_profile_fields() -> None:
    client, service = build_client()

    response = client.post(
        "/me/recommendations",
        json={
            "prompt": "Late night trip hop",
            "seed_ids": [SEED_ID],
            "create_playlist": True,
            "use_openai_agent": True,
            "demo_user_id": "another-account",
        },
    )

    assert response.status_code == 422
    assert service.generate_calls == []


def test_product_recommendation_unknown_session_is_not_disclosed() -> None:
    client, _ = build_client()

    response = client.get("/me/recommendations/40000000-0000-0000-0000-000000000099")

    assert response.status_code == 404
    assert response.json()["code"] == "recommendation_not_found"


def build_client() -> tuple[TestClient, FakeRecommendationService]:
    service = FakeRecommendationService()
    app = create_app(load_env=False, recommendation_service=service)
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


def recommendation_bundle() -> RecommendationSessionBundle:
    now = datetime(2030, 1, 1, tzinfo=UTC)
    session = RecommendationSessionRecord(
        id=SESSION_ID,
        account_id="account-1",
        prompt="Late night trip hop",
        controls={"adventure": "balanced", "allow_explicit": False},
        parsed_intent={"label": "seed-led", "tags": []},
        seed_ids=(SEED_ID,),
        source_snapshot={
            "coverage": {
                "status": "ready",
                "evidence_coverage": 1.0,
            }
        },
        ranking_version="explicit-discovery-v1",
        status="ready",
        generated_at=now,
        updated_at=now,
        reviewed_playlist_name=None,
        reviewed_playlist_public=None,
    )
    item = RecommendationItemRecord(
        session_id=SESSION_ID,
        recording_mbid=RECORDING_MBID,
        spotify_track_id="spotify-1",
        original_rank=1,
        internal_score_components={"total": 0.8},
        evidence={
            "recording_mbid": RECORDING_MBID,
            "evidence_version": "evidence-v1",
            "verifiable": True,
            "reasons": [],
            "limitations": [],
        },
        display_snapshot={
            "spotify_track_id": "spotify-1",
            "name": "Roads",
            "artist_names": ["Portishead"],
            "explicit": False,
            "spotify_url": "https://open.spotify.com/track/spotify-1",
        },
        selected=True,
        reviewed_order=None,
        created_at=now,
    )
    return RecommendationSessionBundle(session=session, items=(item,))
