from __future__ import annotations

from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from fastapi.testclient import TestClient

from music_recommender.api.app import create_app
from music_recommender.api.models import RecommendationRequest
from music_recommender.api.services import DemoApiService
from music_recommender.config import Settings
from music_recommender.recommender.models import UserTasteProfile
from music_recommender.recommender.profile import JsonProfileCache, ProfileSnapshot


def test_recommendations_endpoint_returns_ranked_tracks_with_session() -> None:
    service = FakeApiService()
    client = TestClient(create_app(load_env=False, service=service))

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
    client = TestClient(create_app(load_env=False, service=FakeApiService()))

    response = client.post("/recommendations", json={"prompt": "cheer me up", "limit": 0})

    assert response.status_code == 422


def test_demo_api_service_uses_cached_spotify_profile_affinities(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_table(
        tmp_path / "catalog-run" / "silver" / "tracks" / "dt=2026-07-04" / "part-000.parquet",
        [
            {
                "spotify_track_id": "profile-track",
                "track_name": "Profile Boost",
                "artist_names": ["Profile Artist"],
                "primary_artist_name": "Profile Artist",
                "explicit": False,
                "popularity": 10,
                "spotify_url": "https://open.spotify.com/track/profile-track",
            },
            {
                "spotify_track_id": "generic-track",
                "track_name": "Generic Bright",
                "artist_names": ["Other Artist"],
                "primary_artist_name": "Other Artist",
                "explicit": False,
                "popularity": 10,
                "spotify_url": "https://open.spotify.com/track/generic-track",
            },
        ],
    )
    write_table(
        tmp_path
        / "catalog-run"
        / "silver"
        / "audio_features"
        / "dt=2026-07-04"
        / "part-000.parquet",
        [
            {
                "spotify_track_id": "profile-track",
                "danceability": 0.76,
                "energy": 0.78,
                "valence": 0.88,
            },
            {
                "spotify_track_id": "generic-track",
                "danceability": 0.76,
                "energy": 0.78,
                "valence": 0.88,
            },
        ],
    )
    profile_path = tmp_path / "profile.json"
    JsonProfileCache(profile_path).save(
        ProfileSnapshot(
            profile=UserTasteProfile(
                user_id="12175364859",
                liked_track_ids=("profile-track",),
                known_track_ids=("profile-track",),
                liked_artist_names=("Profile Artist",),
                track_affinity={"profile-track": 1.0},
                artist_affinity={"Profile Artist": 1.0},
            ),
            source="spotify",
            synced_at="2026-07-04T00:00:00Z",
        )
    )
    monkeypatch.setenv("RECOMMENDER_PROFILE_CACHE_PATH", str(profile_path))
    service = DemoApiService(settings_loader=lambda: build_settings(tmp_path))

    response = service.recommend(
        RecommendationRequest(
            prompt="I just broke up and want songs to cheer me up",
            limit=1,
            catalog_run_id="catalog-run",
        )
    )

    assert response["recommendations"][0]["track"]["id"] == "profile-track"


def test_demo_api_service_adds_cached_spotify_profile_candidates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_table(
        tmp_path / "catalog-run" / "silver" / "tracks" / "dt=2026-07-04" / "part-000.parquet",
        [
            {
                "spotify_track_id": "generic-track",
                "track_name": "Generic Bright",
                "artist_names": ["Other Artist"],
                "primary_artist_name": "Other Artist",
                "explicit": False,
                "popularity": 10,
                "spotify_url": "https://open.spotify.com/track/generic-track",
            },
        ],
    )
    write_table(
        tmp_path
        / "catalog-run"
        / "silver"
        / "audio_features"
        / "dt=2026-07-04"
        / "part-000.parquet",
        [
            {
                "spotify_track_id": "generic-track",
                "danceability": 0.76,
                "energy": 0.78,
                "valence": 0.88,
            },
        ],
    )
    profile_path = tmp_path / "profile.json"
    JsonProfileCache(profile_path).save(
        ProfileSnapshot(
            profile=UserTasteProfile(
                user_id="12175364859",
                liked_track_ids=("spotify-only",),
                known_track_ids=("spotify-only",),
                liked_artist_names=("Profile Artist",),
                track_affinity={"spotify-only": 1.0},
                artist_affinity={"Profile Artist": 1.0},
            ),
            source="spotify",
            synced_at="2026-07-04T00:00:00Z",
            spotify_track_candidates=(
                {
                    "id": "spotify-only",
                    "name": "Only In Spotify",
                    "artist_names": ["Profile Artist"],
                    "primary_artist_name": "Profile Artist",
                    "explicit": False,
                    "popularity": 90,
                    "spotify_url": "https://open.spotify.com/track/spotify-only",
                },
            ),
        )
    )
    monkeypatch.setenv("RECOMMENDER_PROFILE_CACHE_PATH", str(profile_path))
    service = DemoApiService(settings_loader=lambda: build_settings(tmp_path))

    response = service.recommend(
        RecommendationRequest(
            prompt="I just broke up and want songs to cheer me up",
            limit=1,
            catalog_run_id="catalog-run",
        )
    )

    assert response["recommendations"][0]["track"] == {
        "id": "spotify-only",
        "name": "Only In Spotify",
        "artist_names": ["Profile Artist"],
        "explicit": False,
        "popularity": 90,
        "spotify_url": "https://open.spotify.com/track/spotify-only",
    }


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


def build_settings(data_root: Path) -> Settings:
    return Settings(
        spotify_client_id="client",
        spotify_client_secret="secret",
        openai_api_key=None,
        openai_agent_model=None,
        aws_region="us-east-1",
        bucket=None,
        spotify_market="US",
        spotify_redirect_uri="http://127.0.0.1:8080/spotify/callback",
        spotify_user_refresh_token=None,
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
        recommender_data_root=data_root,
        recommender_data_mode="local",
        recommender_demo_user_id=None,
        aws_secrets_prefix=None,
    )


def write_table(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(rows)
    pq.write_table(table, path)  # type: ignore[no-untyped-call]
