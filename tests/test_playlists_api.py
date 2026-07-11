from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from music_recommender.api.app import create_app
from music_recommender.api.errors import ApiNotFoundError, ApiValidationError
from music_recommender.api.services import DemoApiService
from music_recommender.config import Settings
from music_recommender.recommender.playlists import JsonPlaylistRecordStore, PlaylistService
from music_recommender.recommender.sessions import (
    JsonRecommendationSessionStore,
    RecommendationSession,
)


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


def test_playlists_endpoint_returns_404_for_unknown_session() -> None:
    client = TestClient(
        create_app(
            load_env=False,
            service=RaisingPlaylistApiService(
                ApiNotFoundError("Recommendation session not found.")
            ),
        )
    )

    response = client.post(
        "/playlists",
        json={
            "session_id": "missing",
            "name": "Breakup Recovery",
            "track_ids": ["sunny"],
        },
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Recommendation session not found."}


def test_playlists_endpoint_returns_400_for_invalid_session_track() -> None:
    client = TestClient(
        create_app(
            load_env=False,
            service=RaisingPlaylistApiService(
                ApiValidationError("Track IDs were not recommended for this session: invented")
            ),
        )
    )

    response = client.post(
        "/playlists",
        json={
            "session_id": "session-1",
            "name": "Breakup Recovery",
            "track_ids": ["invented"],
        },
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": "Track IDs were not recommended for this session: invented"
    }


def test_playlist_service_is_idempotent_by_session(tmp_path: Path) -> None:
    spotify = FakeSpotifyPlaylistClient()
    service = PlaylistService(
        spotify_client=spotify,
        store=JsonPlaylistRecordStore(tmp_path / "playlists.json"),
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


def test_demo_api_service_rejects_playlist_for_unknown_session(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setenv("RECOMMENDER_SESSION_STORE_PATH", str(tmp_path / "sessions.json"))
    monkeypatch.setenv("RECOMMENDER_PLAYLIST_STORE_PATH", str(tmp_path / "playlists.json"))
    spotify = FakeSpotifyPlaylistClient()
    client = TestClient(
        create_app(
            load_env=False,
            service=DemoApiServiceWithFakeSpotify(
                settings_loader=lambda: build_settings(),
                spotify=spotify,
            ),
        )
    )

    response = client.post(
        "/playlists",
        json={
            "session_id": "missing",
            "name": "Breakup Recovery",
            "track_ids": ["sunny"],
        },
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Recommendation session not found: missing"}
    assert spotify.created_count == 0


def test_demo_api_service_rejects_playlist_tracks_outside_session(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    session_path = tmp_path / "sessions.json"
    JsonRecommendationSessionStore(session_path).put(build_session())
    monkeypatch.setenv("RECOMMENDER_SESSION_STORE_PATH", str(session_path))
    monkeypatch.setenv("RECOMMENDER_PLAYLIST_STORE_PATH", str(tmp_path / "playlists.json"))
    spotify = FakeSpotifyPlaylistClient()
    client = TestClient(
        create_app(
            load_env=False,
            service=DemoApiServiceWithFakeSpotify(
                settings_loader=lambda: build_settings(),
                spotify=spotify,
            ),
        )
    )

    response = client.post(
        "/playlists",
        json={
            "session_id": "session-1",
            "name": "Breakup Recovery",
            "track_ids": ["sunny", "invented"],
        },
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": "Track IDs were not recommended for this session: invented"
    }
    assert spotify.created_count == 0


def test_demo_api_service_creates_playlist_for_session_subset_and_records_outcome(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    session_path = tmp_path / "sessions.json"
    JsonRecommendationSessionStore(session_path).put(build_session())
    monkeypatch.setenv("RECOMMENDER_SESSION_STORE_PATH", str(session_path))
    monkeypatch.setenv("RECOMMENDER_PLAYLIST_STORE_PATH", str(tmp_path / "playlists.json"))
    spotify = FakeSpotifyPlaylistClient()
    client = TestClient(
        create_app(
            load_env=False,
            service=DemoApiServiceWithFakeSpotify(
                settings_loader=lambda: build_settings(),
                spotify=spotify,
            ),
        )
    )

    response = client.post(
        "/playlists",
        json={
            "session_id": "session-1",
            "name": "Breakup Recovery",
            "description": "Class demo",
            "track_ids": ["sunny"],
            "public": False,
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["playlist_id"] == "playlist-1"
    assert body["tracks_added"] == ["sunny"]
    assert spotify.added_batches == [["sunny"]]
    session = JsonRecommendationSessionStore(session_path).get("session-1")
    assert session is not None
    assert session.playlist_result is not None
    assert session.playlist_result.playlist_id == "playlist-1"
    assert session.playlist_result.requested_track_ids == ("sunny",)
    assert session.playlist_result.tracks_added == ("sunny",)


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


class RaisingPlaylistApiService:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def create_playlist(self, request: Any) -> dict[str, Any]:
        raise self.error


class DemoApiServiceWithFakeSpotify(DemoApiService):
    def __init__(
        self,
        *,
        settings_loader: Any,
        spotify: FakeSpotifyPlaylistClient,
    ) -> None:
        super().__init__(settings_loader=settings_loader)
        self.spotify = spotify

    def _spotify_user_client(self, settings: Settings) -> Any:
        return self.spotify


class FakeSpotifyPlaylistClient:
    def __init__(self, *, fail_add: bool = False) -> None:
        self.created_count = 0
        self.added_batches: list[list[str]] = []
        self.fail_add = fail_add

    def create_playlist(
        self,
        *,
        name: str,
        description: str = "",
        public: bool = False,
    ) -> dict[str, Any]:
        self.created_count += 1
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


def build_settings() -> Settings:
    return Settings(
        spotify_client_id="client",
        spotify_client_secret="secret",
        openai_api_key=None,
        openai_agent_model=None,
        aws_region="us-east-1",
        bucket=None,
        spotify_market="US",
        spotify_redirect_uri="http://127.0.0.1:8080/spotify/callback",
        spotify_user_refresh_token="refresh",
        spotify_demo_user_id="12175364859",
        spotify_user_scopes=("user-top-read", "user-library-read"),
        max_tracks_per_artist=150,
        enable_spotify_audio_features=False,
        audio_feature_source="reccobeats",
        output_file_format="parquet",
        enable_lyrics_nlp=False,
        lyrics_language_model="fasttext-lid-176",
        lyrics_language_model_path=None,
        lyrics_sentiment_model="cardiffnlp/twitter-xlm-roberta-base-sentiment-multilingual",
        lyrics_nlp_batch_size=8,
        listenbrainz_dump_path=None,
        listenbrainz_user_hash_salt="",
        recommender_data_root="data/local",
        recommender_data_mode="local",
        recommender_demo_user_id=None,
        aws_secrets_prefix=None,
    )
