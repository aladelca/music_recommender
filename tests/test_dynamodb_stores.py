from __future__ import annotations

from typing import Any

from music_recommender.recommender.feedback import FeedbackEvent
from music_recommender.recommender.models import UserTasteProfile
from music_recommender.recommender.playlists import PlaylistRecord
from music_recommender.recommender.profile import ProfileSnapshot
from music_recommender.recommender.sessions import (
    PlaylistResult,
    RecommendationSession,
)
from music_recommender.storage.dynamodb import (
    DynamoDBFeedbackStore,
    DynamoDBPlaylistRecordStore,
    DynamoDBProfileCache,
    DynamoDBRecommendationSessionStore,
)


def test_dynamodb_profile_cache_round_trips_snapshot() -> None:
    client = FakeDynamoDBClient()
    cache = DynamoDBProfileCache(
        table_name="users",
        user_id="12175364859",
        dynamodb_client=client,
    )
    snapshot = ProfileSnapshot(
        profile=UserTasteProfile(
            user_id="12175364859",
            liked_track_ids=("saved-1",),
            known_track_ids=("saved-1",),
            liked_artist_names=("Artist",),
        ),
        source="spotify",
        synced_at="2026-07-09T00:00:00+00:00",
        source_counts={"saved_tracks": 1},
    )

    assert cache.load() is None
    cache.save(snapshot)

    loaded = cache.load()
    assert loaded is not None
    assert loaded.profile.user_id == "12175364859"
    assert loaded.profile.liked_track_ids == ("saved-1",)
    assert loaded.source_counts == {"saved_tracks": 1}
    stored = client.tables["users"]["12175364859"]
    assert "profile_json" in stored
    assert "refresh_token" not in str(stored)


def test_dynamodb_session_store_updates_playlist_result() -> None:
    store = DynamoDBRecommendationSessionStore(
        table_name="sessions",
        dynamodb_client=FakeDynamoDBClient(),
    )
    session = build_session()

    store.put(session)
    loaded = store.get("session-1")
    updated = store.update_playlist_result(
        "session-1",
        PlaylistResult(
            playlist_id="playlist-1",
            url="https://open.spotify.com/playlist/playlist-1",
            requested_track_ids=("sunny",),
            tracks_added=("sunny",),
            snapshot_id="snapshot-1",
            idempotent_replay=False,
        ),
    )

    assert loaded is not None
    assert loaded.recommended_track_ids == ("sunny", "dance")
    assert updated.playlist_result is not None
    assert updated.playlist_result.playlist_id == "playlist-1"
    assert store.get("session-1") == updated


def test_dynamodb_feedback_store_appends_and_lists_by_session() -> None:
    store = DynamoDBFeedbackStore(
        table_name="feedback",
        dynamodb_client=FakeDynamoDBClient(),
    )
    first = FeedbackEvent(
        event_id="event-1",
        session_id="session-1",
        track_id="sunny",
        event_type="like",
        metadata={"source": "test"},
        created_at="2026-07-09T00:00:00+00:00",
    )
    second = FeedbackEvent(
        event_id="event-2",
        session_id="session-2",
        track_id="other",
        event_type="skip",
        metadata={},
        created_at="2026-07-09T00:01:00+00:00",
    )

    store.append(first)
    store.append(second)

    assert store.list_by_session("session-1") == [first]
    assert store.list_all() == [first, second]


def test_dynamodb_playlist_store_is_keyed_by_session() -> None:
    store = DynamoDBPlaylistRecordStore(
        table_name="playlists",
        dynamodb_client=FakeDynamoDBClient(),
    )
    record = PlaylistRecord(
        session_id="session-1",
        playlist_id="playlist-1",
        url="https://open.spotify.com/playlist/playlist-1",
        track_ids=("sunny", "dance"),
        snapshot_id="snapshot-1",
    )

    assert store.get("session-1") is None
    store.put(record)

    loaded = store.get("session-1")
    assert loaded == record


def build_session() -> RecommendationSession:
    return RecommendationSession(
        session_id="session-1",
        user_id="12175364859",
        prompt="cheer me up",
        intent={"label": "cheer-up"},
        recommended_track_ids=("sunny", "dance"),
        recommendations=({"track": {"id": "sunny"}, "score": {"total": 0.9}},),
        catalog_run_id="catalog-run",
        interaction_run_id=None,
        playlist_candidate={"track_ids": ["sunny", "dance"]},
        created_at="2026-07-09T00:00:00+00:00",
        updated_at="2026-07-09T00:00:00+00:00",
    )


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
        key = _key_value(Key)
        item = table.get(key)
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
