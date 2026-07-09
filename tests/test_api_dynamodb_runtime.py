from __future__ import annotations

from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from music_recommender.api.models import (
    FeedbackRequest,
    PlaylistCreateRequest,
    ProfileSyncRequest,
    RecommendationRequest,
)
from music_recommender.api.services import DemoApiService
from music_recommender.config import Settings
from music_recommender.recommender.sessions import RecommendationSession
from music_recommender.storage.dynamodb import (
    DynamoDBFeedbackStore,
    DynamoDBPlaylistRecordStore,
    DynamoDBProfileCache,
    DynamoDBRecommendationSessionStore,
)


def test_demo_api_service_uses_dynamodb_runtime_stores_for_recommendations(
    tmp_path: Path,
) -> None:
    fake_dynamodb = FakeDynamoDBClient()
    write_catalog(tmp_path)
    service = DemoApiService(
        settings_loader=lambda: build_dynamodb_settings(tmp_path),
        dynamodb_client_factory=lambda: fake_dynamodb,
    )

    response = service.recommend(
        RecommendationRequest(
            prompt="I just broke up and want songs to cheer me up",
            limit=1,
            catalog_run_id="catalog-run",
        )
    )

    session = DynamoDBRecommendationSessionStore(
        table_name="sessions",
        dynamodb_client=fake_dynamodb,
    ).get(str(response["session_id"]))
    assert session is not None
    assert session.prompt == "I just broke up and want songs to cheer me up"
    assert session.recommended_track_ids == ("sunny",)


def test_demo_api_service_uses_dynamodb_profile_cache_for_sync_and_status() -> None:
    fake_dynamodb = FakeDynamoDBClient()
    service = DemoApiServiceWithFakeSpotify(
        settings_loader=lambda: build_dynamodb_settings(Path("data/local")),
        dynamodb_client_factory=lambda: fake_dynamodb,
        spotify=FakeSpotifyProfileClient(),
    )

    sync_payload = service.sync_profile(ProfileSyncRequest(top_limit=1, saved_limit=1))
    status_payload = service.get_profile_status()

    assert sync_payload["profile"]["liked_track_ids"] == ["saved-1", "top-1"]
    assert status_payload["present"] is True
    cache = DynamoDBProfileCache(
        table_name="users",
        user_id="12175364859",
        dynamodb_client=fake_dynamodb,
    )
    assert cache.load() is not None


def test_demo_api_service_uses_dynamodb_feedback_store() -> None:
    fake_dynamodb = FakeDynamoDBClient()
    session_store = DynamoDBRecommendationSessionStore(
        table_name="sessions",
        dynamodb_client=fake_dynamodb,
    )
    session_store.put(build_session())
    service = DemoApiService(
        settings_loader=lambda: build_dynamodb_settings(Path("data/local")),
        dynamodb_client_factory=lambda: fake_dynamodb,
    )

    payload = service.record_feedback(
        FeedbackRequest(
            session_id="session-1",
            track_id="sunny",
            event_type="like",
            metadata={"source": "test"},
        )
    )

    assert payload["status"] == "recorded"
    events = DynamoDBFeedbackStore(
        table_name="feedback",
        dynamodb_client=fake_dynamodb,
    ).list_by_session("session-1")
    assert len(events) == 1
    assert events[0].track_id == "sunny"
    assert events[0].metadata == {"source": "test"}


def test_demo_api_service_uses_dynamodb_playlist_store_and_updates_session() -> None:
    fake_dynamodb = FakeDynamoDBClient()
    session_store = DynamoDBRecommendationSessionStore(
        table_name="sessions",
        dynamodb_client=fake_dynamodb,
    )
    session_store.put(build_session())
    spotify = FakeSpotifyPlaylistClient()
    service = DemoApiServiceWithFakeSpotify(
        settings_loader=lambda: build_dynamodb_settings(Path("data/local")),
        dynamodb_client_factory=lambda: fake_dynamodb,
        spotify=spotify,
    )

    payload = service.create_playlist(
        PlaylistCreateRequest(
            session_id="session-1",
            name="Breakup Recovery",
            description="Class demo",
            track_ids=["sunny"],
            public=False,
        )
    )

    assert payload["playlist_id"] == "playlist-1"
    assert spotify.created_count == 1
    playlist_record = DynamoDBPlaylistRecordStore(
        table_name="playlists",
        dynamodb_client=fake_dynamodb,
    ).get("session-1")
    assert playlist_record is not None
    assert playlist_record.track_ids == ("sunny",)
    updated_session = session_store.get("session-1")
    assert updated_session is not None
    assert updated_session.playlist_result is not None
    assert updated_session.playlist_result.playlist_id == "playlist-1"


class DemoApiServiceWithFakeSpotify(DemoApiService):
    def __init__(
        self,
        *,
        settings_loader: Any,
        dynamodb_client_factory: Any,
        spotify: Any,
    ) -> None:
        super().__init__(
            settings_loader=settings_loader,
            dynamodb_client_factory=dynamodb_client_factory,
        )
        self.spotify = spotify

    def _spotify_user_client(self, settings: Settings) -> Any:
        return self.spotify


class FakeSpotifyProfileClient:
    def get_current_user_profile(self) -> dict[str, Any]:
        return {"id": "12175364859", "account_id": "stable-account"}

    def iter_saved_tracks(
        self,
        *,
        limit_total: int,
        page_size: int = 50,
        market: str | None = None,
    ) -> list[dict[str, Any]]:
        return [{"track": {"id": "saved-1", "artists": [{"name": "Saved Artist"}]}}]

    def iter_top_items(
        self,
        item_type: str,
        *,
        limit_total: int,
        time_range: str = "medium_term",
        page_size: int = 50,
    ) -> list[dict[str, Any]]:
        if item_type == "tracks":
            return [{"id": "top-1", "artists": [{"name": "Top Artist"}]}]
        if item_type == "artists":
            return [{"name": "Top Artist"}]
        raise AssertionError(f"Unexpected item type: {item_type}")

    def iter_current_user_playlists(
        self,
        *,
        limit_total: int,
        page_size: int = 50,
    ) -> list[dict[str, Any]]:
        return []

    def iter_playlist_items(
        self,
        playlist_id: str,
        *,
        limit_total: int,
        page_size: int = 50,
        market: str | None = None,
        fields: str | None = None,
    ) -> list[dict[str, Any]]:
        return []

    def get_recently_played(
        self,
        *,
        limit: int = 20,
        before: int | None = None,
        after: int | None = None,
    ) -> dict[str, Any]:
        return {"items": []}


class FakeSpotifyPlaylistClient:
    def __init__(self) -> None:
        self.created_count = 0

    def create_playlist(
        self,
        user_id: str,
        *,
        name: str,
        description: str = "",
        public: bool = False,
    ) -> dict[str, Any]:
        self.created_count += 1
        return {
            "id": "playlist-1",
            "external_urls": {"spotify": "https://open.spotify.com/playlist/playlist-1"},
        }

    def add_playlist_items(self, playlist_id: str, track_ids_or_uris: list[str]) -> dict[str, Any]:
        return {"snapshot_id": "snapshot-1"}


class FakeDynamoDBClient:
    def __init__(self) -> None:
        self.tables: dict[str, dict[str, dict[str, dict[str, str]]]] = {}

    def get_item(
        self,
        *,
        TableName: str,
        Key: dict[str, dict[str, str]],
    ) -> dict[str, Any]:
        table = self.tables.setdefault(TableName, {})
        item = table.get(_key_value(Key))
        return {"Item": item} if item is not None else {}

    def put_item(
        self,
        *,
        TableName: str,
        Item: dict[str, dict[str, str]],
    ) -> dict[str, Any]:
        table = self.tables.setdefault(TableName, {})
        table[_item_key(Item)] = Item
        return {}

    def query(
        self,
        *,
        TableName: str,
        KeyConditionExpression: str,
        ExpressionAttributeValues: dict[str, dict[str, str]],
    ) -> dict[str, Any]:
        assert KeyConditionExpression == "session_id = :session_id"
        session_id = ExpressionAttributeValues[":session_id"]["S"]
        table = self.tables.setdefault(TableName, {})
        return {
            "Items": [
                item for item in table.values() if item.get("session_id", {}).get("S") == session_id
            ]
        }

    def scan(self, *, TableName: str) -> dict[str, Any]:
        table = self.tables.setdefault(TableName, {})
        return {"Items": list(table.values())}


def build_dynamodb_settings(data_root: Path) -> Settings:
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
        recommender_data_root=data_root,
        recommender_data_mode="local",
        recommender_demo_user_id=None,
        aws_secrets_prefix=None,
        runtime_store_backend="dynamodb",
        users_table_name="users",
        sessions_table_name="sessions",
        feedback_table_name="feedback",
        playlists_table_name="playlists",
    )


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
        created_at="2026-07-09T00:00:00+00:00",
        updated_at="2026-07-09T00:00:00+00:00",
    )


def write_catalog(tmp_path: Path) -> None:
    write_table(
        tmp_path / "catalog-run" / "silver" / "tracks" / "dt=2026-07-09" / "part-000.parquet",
        [
            {
                "spotify_track_id": "sunny",
                "track_name": "Sunny Recovery",
                "artist_names": ["Dua Lipa"],
                "primary_artist_name": "Dua Lipa",
                "explicit": False,
                "popularity": 80,
                "spotify_url": "https://open.spotify.com/track/sunny",
            },
        ],
    )
    write_table(
        tmp_path
        / "catalog-run"
        / "silver"
        / "audio_features"
        / "dt=2026-07-09"
        / "part-000.parquet",
        [
            {
                "spotify_track_id": "sunny",
                "danceability": 0.76,
                "energy": 0.78,
                "valence": 0.88,
            },
        ],
    )


def write_table(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(rows)
    pq.write_table(table, path)  # type: ignore[no-untyped-call]


def _key_value(key: dict[str, dict[str, str]]) -> str:
    if "session_id" in key and "event_key" in key:
        return f"{key['session_id']['S']}#{key['event_key']['S']}"
    if "session_id" in key:
        return key["session_id"]["S"]
    if "user_id" in key:
        return key["user_id"]["S"]
    raise AssertionError(f"Unexpected key: {key}")


def _item_key(item: dict[str, dict[str, str]]) -> str:
    if "session_id" in item and "event_key" in item:
        return f"{item['session_id']['S']}#{item['event_key']['S']}"
    if "session_id" in item:
        return item["session_id"]["S"]
    if "user_id" in item:
        return item["user_id"]["S"]
    raise AssertionError(f"Unexpected item: {item}")
