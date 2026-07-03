from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from music_recommender.api.app import create_app


def test_recommendations_endpoint_returns_ranked_tracks_with_session() -> None:
    service = FakeApiService()
    client = TestClient(create_app(service=service))

    response = client.post(
        "/recommendations",
        json={
            "prompt": "I just broke up and want songs to cheer me up",
            "limit": 2,
            "liked_artist_names": ["Dua Lipa"],
            "create_playlist": True,
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["session_id"] == "session-1"
    assert body["intent"]["label"] == "cheer-up"
    assert [item["track"]["id"] for item in body["recommendations"]] == ["sunny"]
    assert body["playlist_candidate"]["track_ids"] == ["sunny"]
    assert service.recommendation_request == {
        "prompt": "I just broke up and want songs to cheer me up",
        "limit": 2,
        "create_playlist": True,
        "use_openai_agent": False,
        "catalog_run_id": None,
        "interaction_run_id": None,
        "demo_user_id": None,
        "liked_artist_names": ["Dua Lipa"],
        "liked_track_ids": [],
        "known_track_ids": [],
        "blocked_artist_names": [],
    }


def test_recommendations_endpoint_validates_limit() -> None:
    client = TestClient(create_app(service=FakeApiService()))

    response = client.post("/recommendations", json={"prompt": "cheer me up", "limit": 0})

    assert response.status_code == 422


class FakeApiService:
    def __init__(self) -> None:
        self.recommendation_request: dict[str, Any] | None = None

    def recommend(self, request: Any) -> dict[str, Any]:
        self.recommendation_request = request.model_dump()
        return {
            "session_id": "session-1",
            "prompt": request.prompt,
            "intent": {
                "label": "cheer-up",
                "target_valence": 0.88,
                "target_energy": 0.78,
                "target_danceability": 0.76,
                "allow_explicit": True,
                "blocked_artist_names": [],
                "rationale": "Parsed from test prompt.",
            },
            "recommendations": [
                {
                    "track": {
                        "id": "sunny",
                        "name": "Sunny Recovery",
                        "artist_names": ["Dua Lipa"],
                        "explicit": False,
                        "popularity": 80,
                        "spotify_url": "https://open.spotify.com/track/sunny",
                    },
                    "score": {
                        "mood_fit": 0.95,
                        "taste_affinity": 0.2,
                        "novelty_bonus": 0.1,
                        "popularity_prior": 0.8,
                        "diversity_penalty": 0.0,
                        "total": 1.55,
                    },
                    "explanation": "Bright, high-energy track.",
                }
            ],
            "playlist_candidate": {
                "name": "Music Recommender - cheer-up",
                "description": "Generated from prompt: " + request.prompt,
                "track_ids": ["sunny"],
            },
        }
