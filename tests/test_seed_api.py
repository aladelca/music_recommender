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
from music_recommender.sources.musicbrainz import MusicBrainzSearchResult
from music_recommender.storage.protocols import UserSeedRecord


class FakePage:
    def to_dict(self) -> dict[str, Any]:
        return {
            "results": [
                MusicBrainzSearchResult(
                    mbid="8ab7aa79-24a4-4a5f-b2c6-3e3c2c7af95c",
                    entity_type="artist",
                    name="Portishead",
                    artist_credit=(),
                    release_data={"country": "GB"},
                    isrcs=(),
                ).to_dict()
            ],
            "source": "musicbrainz",
            "cached": False,
        }


class FakeSeedService:
    def __init__(self) -> None:
        self.search_calls: list[dict[str, Any]] = []
        self.replace_calls: list[dict[str, Any]] = []
        self.seeds = (
            UserSeedRecord(
                id="seed-1",
                account_id="account-1",
                entity_type="artist",
                mbid="8ab7aa79-24a4-4a5f-b2c6-3e3c2c7af95c",
                display_name="Portishead",
                position=1,
                selected_at=datetime(2030, 1, 1, tzinfo=UTC),
            ),
        )

    def search(self, **kwargs: Any) -> FakePage:
        self.search_calls.append(kwargs)
        return FakePage()

    def replace(self, **kwargs: Any) -> tuple[UserSeedRecord, ...]:
        self.replace_calls.append(kwargs)
        return self.seeds

    def list(self, **kwargs: Any) -> tuple[UserSeedRecord, ...]:
        assert kwargs == {"account_id": "account-1"}
        return self.seeds


def test_music_search_uses_approved_current_user_and_bounded_contract() -> None:
    client, service = build_client()

    response = client.get("/music/search", params={"q": "Portishead", "type": "artist"})

    assert response.status_code == 200
    assert response.json()["source"] == "musicbrainz"
    assert response.json()["results"][0]["name"] == "Portishead"
    assert service.search_calls == [{"query": "Portishead", "entity_type": "artist"}]


def test_replace_and_list_seeds_derive_account_from_session() -> None:
    client, service = build_client()
    payload = {
        "seeds": [
            {
                "entity_type": "artist",
                "mbid": "8ab7aa79-24a4-4a5f-b2c6-3e3c2c7af95c",
            }
        ]
    }

    replaced = client.put("/me/seeds", json=payload)
    listed = client.get("/me/seeds")

    assert replaced.status_code == 200
    assert replaced.json() == listed.json()
    assert replaced.json()["seeds"][0]["source"] == "musicbrainz"
    assert "account_id" not in replaced.json()["seeds"][0]
    assert service.replace_calls[0]["account_id"] == "account-1"
    assert service.replace_calls[0]["selections"][0].mbid == payload["seeds"][0]["mbid"]


def test_seed_api_rejects_unbounded_input_before_service_call() -> None:
    client, service = build_client()

    short_query = client.get("/music/search", params={"q": "x", "type": "artist"})
    too_many = client.put(
        "/me/seeds",
        json={
            "seeds": [
                {
                    "entity_type": "artist",
                    "mbid": f"00000000-0000-0000-0000-{index:012d}",
                }
                for index in range(6)
            ]
        },
    )

    assert short_query.status_code == 422
    assert too_many.status_code == 422
    assert service.search_calls == []
    assert service.replace_calls == []


def build_client() -> tuple[TestClient, FakeSeedService]:
    service = FakeSeedService()
    app = create_app(load_env=False, seed_service=service)
    user = ProductUser(
        account_id="account-1",
        display_name="Tester",
        access_status="approved",
        seed_ready=False,
        reauthorization_required=False,
    )
    app.dependency_overrides[require_approved_user] = lambda: user
    app.dependency_overrides[require_approved_mutating_user] = lambda: user
    return TestClient(app), service
