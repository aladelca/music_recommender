from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from music_recommender.api.app import create_app
from music_recommender.recommender.profile import JsonProfileCache, SpotifyProfileSyncService


def test_profile_sync_and_status_routes() -> None:
    service = FakeApiService()
    client = TestClient(create_app(load_env=False, service=service))

    sync_response = client.post("/profile/sync", json={"top_limit": 2, "saved_limit": 2})
    status_response = client.get("/profile")

    assert sync_response.status_code == 200, sync_response.text
    assert sync_response.json()["profile"]["user_id"] == "12175364859"
    assert sync_response.json()["profile"]["liked_track_ids"] == ["top-1", "saved-1"]
    assert status_response.status_code == 200
    assert status_response.json()["present"] is True


def test_profile_sync_service_normalizes_spotify_profile(tmp_path: Path) -> None:
    service = SpotifyProfileSyncService(
        spotify_client=FakeSpotifyProfileClient(),
        cache=JsonProfileCache(tmp_path / "profile.json"),
        required_user_id="12175364859",
    )

    snapshot = service.sync_profile(top_limit=2, saved_limit=2)
    cached = service.get_cached_profile()

    assert snapshot.profile.user_id == "12175364859"
    assert snapshot.profile.liked_track_ids == ("top-1", "saved-1")
    assert snapshot.profile.known_track_ids == ("top-1", "saved-1")
    assert snapshot.profile.liked_artist_names == ("Dua Lipa", "Robyn")
    assert cached is not None
    assert cached.profile == snapshot.profile


class FakeApiService:
    def sync_profile(self, request: Any) -> dict[str, Any]:
        assert request.top_limit == 2
        assert request.saved_limit == 2
        return {
            "profile": {
                "user_id": "12175364859",
                "liked_track_ids": ["top-1", "saved-1"],
                "known_track_ids": ["top-1", "saved-1"],
                "liked_artist_names": ["Dua Lipa", "Robyn"],
                "blocked_artist_names": [],
            },
            "source": "spotify",
            "synced_at": "2026-07-03T23:00:00Z",
        }

    def get_profile_status(self) -> dict[str, Any]:
        return {
            "present": True,
            "profile": {
                "user_id": "12175364859",
                "liked_track_ids": ["top-1", "saved-1"],
                "known_track_ids": ["top-1", "saved-1"],
                "liked_artist_names": ["Dua Lipa", "Robyn"],
                "blocked_artist_names": [],
            },
            "synced_at": "2026-07-03T23:00:00Z",
        }


class FakeSpotifyProfileClient:
    def get_current_user_profile(self) -> dict[str, Any]:
        return {"id": "12175364859"}

    def get_top_items(
        self,
        item_type: str,
        *,
        limit: int = 20,
        offset: int = 0,
        time_range: str = "medium_term",
    ) -> dict[str, Any]:
        assert offset == 0
        assert time_range == "medium_term"
        if item_type == "tracks":
            assert limit == 2
            return {
                "items": [
                    {"id": "top-1", "artists": [{"name": "Dua Lipa"}]},
                    {"id": "saved-1", "artists": [{"name": "Dua Lipa"}]},
                ]
            }
        if item_type == "artists":
            assert limit == 2
            return {"items": [{"name": "Dua Lipa"}, {"name": "Robyn"}]}
        raise AssertionError(f"Unexpected top item type: {item_type}")

    def get_saved_tracks(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        market: str | None = None,
    ) -> dict[str, Any]:
        assert limit == 2
        assert offset == 0
        assert market is None
        return {"items": [{"track": {"id": "saved-1", "artists": [{"name": "Robyn"}]}}]}
