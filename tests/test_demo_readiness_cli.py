from __future__ import annotations

from typing import Any

from music_recommender.config import Settings
from music_recommender.demo_readiness_cli import (
    _live_profile_check_payload,
    _profile_required_scopes,
    _s3_data_check_payload,
)


def test_profile_required_scopes_include_playlist_reads_when_requested() -> None:
    settings = build_settings()

    assert _profile_required_scopes(
        settings,
        include_playlists=True,
        include_recently_played=True,
    ) == (
        "playlist-read-private",
        "user-library-read",
        "user-read-recently-played",
        "user-top-read",
    )


def test_live_profile_check_payload_uses_redacted_spotify_samples() -> None:
    payload = _live_profile_check_payload(
        build_settings(),
        client=FakeSpotifyUserClient(),
        include_playlists=True,
        include_recently_played=True,
        sample_limit=2,
    )

    assert payload == {
        "account_id_present": True,
        "missing_required_scopes": [],
        "playlist_sample_count": 1,
        "recent_track_sample_count": 1,
        "saved_track_sample_count": 2,
        "top_artist_sample_count": 1,
        "top_track_sample_count": 1,
        "user_id": "12175364859",
    }


def test_s3_data_check_payload_includes_profile_summary_when_requested(
    monkeypatch: Any,
) -> None:
    calls: list[dict[str, Any]] = []

    def fake_check_s3_recommender_data(
        data_root: str,
        *,
        run_id: str,
        required_datasets: tuple[str, ...] = ("silver/tracks", "silver/audio_features"),
    ) -> FakeReadiness:
        calls.append(
            {
                "data_root": data_root,
                "run_id": run_id,
                "required_datasets": required_datasets,
            }
        )
        return FakeReadiness(root=data_root, run_id=run_id, datasets=required_datasets)

    monkeypatch.setattr(
        "music_recommender.demo_readiness_cli.check_s3_recommender_data",
        fake_check_s3_recommender_data,
    )

    payload = _s3_data_check_payload(
        "s3://bucket",
        catalog_run_id="catalog-run",
        profile_run_id="profile-run",
    )

    assert payload["catalog"]["run_id"] == "catalog-run"
    assert payload["profile"]["run_id"] == "profile-run"
    assert calls == [
        {
            "data_root": "s3://bucket",
            "run_id": "catalog-run",
            "required_datasets": ("silver/tracks", "silver/audio_features"),
        },
        {
            "data_root": "s3://bucket",
            "run_id": "profile-run",
            "required_datasets": (
                "silver/user_profile_track_signals",
                "silver/user_profile_artist_signals",
                "gold/user_profile_track_interactions",
            ),
        },
    ]


class FakeSpotifyUserClient:
    def refresh_access_token(self, *, required_scopes: tuple[str, ...] = ()) -> Any:
        assert "user-library-read" in required_scopes
        assert "playlist-read-private" in required_scopes
        return object()

    def get_current_user_profile(self) -> dict[str, Any]:
        return {"id": "12175364859", "account_id": "stable-account"}

    def get_saved_tracks(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        market: str | None = None,
    ) -> dict[str, Any]:
        assert limit == 2
        return {"items": [{"track": {"id": "saved-1"}}, {"track": {"id": "saved-2"}}]}

    def get_top_items(
        self,
        item_type: str,
        *,
        limit: int = 20,
        offset: int = 0,
        time_range: str = "medium_term",
    ) -> dict[str, Any]:
        assert limit == 2
        if item_type == "tracks":
            return {"items": [{"id": "top-1"}]}
        if item_type == "artists":
            return {"items": [{"id": "artist-1"}]}
        raise AssertionError(f"Unexpected item type: {item_type}")

    def get_current_user_playlists(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        assert limit == 2
        return {"items": [{"id": "playlist-1"}]}

    def get_recently_played(
        self,
        *,
        limit: int = 20,
        before: int | None = None,
        after: int | None = None,
    ) -> dict[str, Any]:
        assert limit == 2
        return {"items": [{"track": {"id": "recent-1"}}]}


class FakeReadiness:
    def __init__(self, *, root: str, run_id: str, datasets: tuple[str, ...]) -> None:
        self.root = root
        self.run_id = run_id
        self.datasets = datasets

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": self.root,
            "run_id": self.run_id,
            "ready": True,
            "datasets": {dataset: {"row_count": 1} for dataset in self.datasets},
        }


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
        spotify_user_scopes=(
            "user-top-read",
            "user-library-read",
            "playlist-read-private",
            "playlist-modify-private",
            "playlist-modify-public",
        ),
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
