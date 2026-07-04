from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from music_recommender.api.app import create_app
from music_recommender.recommender.playlists import JsonPlaylistRecordStore, PlaylistService


def test_playlists_endpoint_creates_playlist_through_service() -> None:
    service = FakeApiService()
    client = TestClient(create_app(load_env=False, service=service))

    response = client.post(
        "/playlists",
        json={
            "session_id": "session-1",
            "name": "Breakup Recovery",
            "description": "Class demo",
            "track_ids": ["sunny", "dance"],
            "public": False,
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["playlist_id"] == "playlist-1"
    assert body["tracks_added"] == ["sunny", "dance"]
    assert body["idempotent_replay"] is False
    assert service.playlist_request == {
        "session_id": "session-1",
        "name": "Breakup Recovery",
        "description": "Class demo",
        "track_ids": ["sunny", "dance"],
        "public": False,
    }


def test_playlist_service_is_idempotent_by_session(tmp_path: Path) -> None:
    spotify = FakeSpotifyPlaylistClient()
    service = PlaylistService(
        spotify_client=spotify,
        store=JsonPlaylistRecordStore(tmp_path / "playlists.json"),
        user_id="12175364859",
    )

    first = service.create_playlist(
        session_id="session-1",
        name="Breakup Recovery",
        description="Class demo",
        track_ids=("sunny", "dance"),
        public=False,
    )
    second = service.create_playlist(
        session_id="session-1",
        name="Breakup Recovery",
        description="Class demo",
        track_ids=("sunny", "dance"),
        public=False,
    )

    assert first.idempotent_replay is False
    assert second.idempotent_replay is True
    assert second.playlist_id == first.playlist_id
    assert spotify.created_count == 1
    assert spotify.added_batches == [["sunny", "dance"]]


def test_playlist_service_does_not_create_duplicate_playlist_after_add_failure(
    tmp_path: Path,
) -> None:
    spotify = FakeSpotifyPlaylistClient(fail_add=True)
    service = PlaylistService(
        spotify_client=spotify,
        store=JsonPlaylistRecordStore(tmp_path / "playlists.json"),
        user_id="12175364859",
    )

    first = service.create_playlist(
        session_id="session-1",
        name="Breakup Recovery",
        description="Class demo",
        track_ids=("sunny", "dance"),
        public=False,
    )
    second = service.create_playlist(
        session_id="session-1",
        name="Breakup Recovery",
        description="Class demo",
        track_ids=("sunny", "dance"),
        public=False,
    )

    assert first.idempotent_replay is False
    assert first.tracks_added == ()
    assert first.partial_failures == ("spotify add failed",)
    assert second.idempotent_replay is True
    assert second.playlist_id == first.playlist_id
    assert second.partial_failures == ("spotify add failed",)
    assert spotify.created_count == 1


class FakeApiService:
    def __init__(self) -> None:
        self.playlist_request: dict[str, Any] | None = None

    def create_playlist(self, request: Any) -> dict[str, Any]:
        self.playlist_request = request.model_dump()
        return {
            "session_id": request.session_id,
            "playlist_id": "playlist-1",
            "url": "https://open.spotify.com/playlist/playlist-1",
            "tracks_added": request.track_ids,
            "snapshot_id": "snapshot-1",
            "idempotent_replay": False,
            "partial_failures": [],
        }


class FakeSpotifyPlaylistClient:
    def __init__(self, *, fail_add: bool = False) -> None:
        self.created_count = 0
        self.added_batches: list[list[str]] = []
        self.fail_add = fail_add

    def create_playlist(
        self,
        user_id: str,
        *,
        name: str,
        description: str = "",
        public: bool = False,
    ) -> dict[str, Any]:
        self.created_count += 1
        assert user_id == "12175364859"
        assert name == "Breakup Recovery"
        assert description == "Class demo"
        assert public is False
        return {
            "id": "playlist-1",
            "external_urls": {"spotify": "https://open.spotify.com/playlist/playlist-1"},
        }

    def add_playlist_items(self, playlist_id: str, track_ids_or_uris: list[str]) -> dict[str, Any]:
        assert playlist_id == "playlist-1"
        if self.fail_add:
            raise RuntimeError("spotify add failed")
        self.added_batches.append(track_ids_or_uris)
        return {"snapshot_id": "snapshot-1"}
