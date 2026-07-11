from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from music_recommender.api.app import create_app
from music_recommender.api.dependencies import (
    require_approved_mutating_user,
    require_approved_user,
)
from music_recommender.auth.models import ProductUser

ARTIST_MBID = "00000000-0000-0000-0000-000000000001"


class FakePreferenceService:
    def __init__(self) -> None:
        self.unblocked: list[dict[str, Any]] = []

    def get_preferences(self, *, account_id: str) -> dict[str, Any]:
        assert account_id == "account-1"
        return payload()

    def unblock_artist(self, **kwargs: Any) -> dict[str, Any]:
        self.unblocked.append(kwargs)
        return {**payload(), "blocked_artists": []}


def test_preferences_are_account_scoped_and_artist_unblock_is_mutating() -> None:
    service = FakePreferenceService()
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
    client = TestClient(app)

    listed = client.get("/me/preferences")
    removed = client.delete(f"/me/preferences/artists/{ARTIST_MBID}")

    assert listed.status_code == 200
    assert listed.json()["blocked_artists"][0]["name"] == "Portishead"
    assert removed.status_code == 200
    assert removed.json()["blocked_artists"] == []
    assert service.unblocked == [{"account_id": "account-1", "artist_mbid": ARTIST_MBID}]
    assert "account_id" not in listed.text


def payload() -> dict[str, Any]:
    return {
        "allow_explicit": True,
        "blocked_artists": [{"mbid": ARTIST_MBID, "name": "Portishead"}],
        "blocked_recordings": [],
    }
