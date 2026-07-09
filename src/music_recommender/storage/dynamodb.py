from __future__ import annotations

import json
from typing import Any

from music_recommender.models import JsonDict
from music_recommender.recommender.feedback import (
    FeedbackEvent,
    feedback_event_from_dict,
)
from music_recommender.recommender.playlists import (
    PlaylistRecord,
    playlist_record_from_dict,
)
from music_recommender.recommender.profile import (
    ProfileSnapshot,
    profile_snapshot_from_dict,
)
from music_recommender.recommender.sessions import (
    PlaylistResult,
    RecommendationSession,
    recommendation_session_from_dict,
)


class DynamoDBProfileCache:
    def __init__(
        self,
        *,
        table_name: str,
        user_id: str,
        dynamodb_client: Any | None = None,
    ) -> None:
        self.table_name = table_name
        self.user_id = user_id
        self.dynamodb_client = dynamodb_client or _default_dynamodb_client()

    def load(self) -> ProfileSnapshot | None:
        response = self.dynamodb_client.get_item(
            TableName=self.table_name,
            Key={"user_id": _string_attr(self.user_id)},
        )
        item = response.get("Item")
        if not isinstance(item, dict) or "profile_json" not in item:
            return None
        return profile_snapshot_from_dict(_json_attr_value(item["profile_json"]))

    def save(self, snapshot: ProfileSnapshot) -> None:
        user_id = snapshot.spotify_user_id or snapshot.profile.user_id or self.user_id
        self.dynamodb_client.put_item(
            TableName=self.table_name,
            Item={
                "user_id": _string_attr(user_id),
                "record_type": _string_attr("profile_cache"),
                "profile_json": _json_attr(snapshot.to_dict()),
                "updated_at": _string_attr(snapshot.synced_at),
            },
        )


class DynamoDBRecommendationSessionStore:
    def __init__(
        self,
        *,
        table_name: str,
        dynamodb_client: Any | None = None,
    ) -> None:
        self.table_name = table_name
        self.dynamodb_client = dynamodb_client or _default_dynamodb_client()

    def get(self, session_id: str) -> RecommendationSession | None:
        response = self.dynamodb_client.get_item(
            TableName=self.table_name,
            Key={"session_id": _string_attr(session_id)},
        )
        item = response.get("Item")
        if not isinstance(item, dict) or "session_json" not in item:
            return None
        return recommendation_session_from_dict(_json_attr_value(item["session_json"]))

    def put(self, session: RecommendationSession) -> None:
        self.dynamodb_client.put_item(
            TableName=self.table_name,
            Item={
                "session_id": _string_attr(session.session_id),
                "user_id": _string_attr(session.user_id),
                "session_json": _json_attr(session.to_dict()),
                "updated_at": _string_attr(session.updated_at),
            },
        )

    def update_playlist_result(
        self,
        session_id: str,
        playlist_result: PlaylistResult,
    ) -> RecommendationSession:
        session = self.get(session_id)
        if session is None:
            raise KeyError(session_id)
        updated = session.with_playlist_result(playlist_result)
        self.put(updated)
        return updated


class DynamoDBFeedbackStore:
    def __init__(
        self,
        *,
        table_name: str,
        dynamodb_client: Any | None = None,
    ) -> None:
        self.table_name = table_name
        self.dynamodb_client = dynamodb_client or _default_dynamodb_client()

    def append(self, event: FeedbackEvent) -> None:
        self.dynamodb_client.put_item(
            TableName=self.table_name,
            Item={
                "session_id": _string_attr(event.session_id),
                "event_key": _string_attr(_feedback_event_key(event)),
                "event_id": _string_attr(event.event_id),
                "event_json": _json_attr(event.to_dict()),
                "created_at": _string_attr(event.created_at),
            },
        )

    def list_all(self) -> list[FeedbackEvent]:
        response = self.dynamodb_client.scan(TableName=self.table_name)
        return _feedback_events_from_items(response.get("Items", []))

    def list_by_session(self, session_id: str) -> list[FeedbackEvent]:
        response = self.dynamodb_client.query(
            TableName=self.table_name,
            KeyConditionExpression="session_id = :session_id",
            ExpressionAttributeValues={":session_id": _string_attr(session_id)},
        )
        return _feedback_events_from_items(response.get("Items", []))


class DynamoDBPlaylistRecordStore:
    def __init__(
        self,
        *,
        table_name: str,
        dynamodb_client: Any | None = None,
    ) -> None:
        self.table_name = table_name
        self.dynamodb_client = dynamodb_client or _default_dynamodb_client()

    def get(self, session_id: str) -> PlaylistRecord | None:
        response = self.dynamodb_client.get_item(
            TableName=self.table_name,
            Key={"session_id": _string_attr(session_id)},
        )
        item = response.get("Item")
        if not isinstance(item, dict) or "playlist_json" not in item:
            return None
        return playlist_record_from_dict(_json_attr_value(item["playlist_json"]))

    def put(self, record: PlaylistRecord) -> None:
        self.dynamodb_client.put_item(
            TableName=self.table_name,
            Item={
                "session_id": _string_attr(record.session_id),
                "playlist_id": _string_attr(record.playlist_id),
                "playlist_json": _json_attr(record.to_dict()),
            },
        )


def _feedback_events_from_items(items: object) -> list[FeedbackEvent]:
    if not isinstance(items, list):
        return []
    events = [
        feedback_event_from_dict(_json_attr_value(item["event_json"]))
        for item in items
        if isinstance(item, dict) and "event_json" in item
    ]
    return sorted(events, key=lambda event: (event.created_at, event.event_id))


def _feedback_event_key(event: FeedbackEvent) -> str:
    return f"{event.created_at}#{event.event_id}"


def _string_attr(value: str) -> dict[str, str]:
    return {"S": value}


def _json_attr(payload: JsonDict) -> dict[str, str]:
    return {"S": json.dumps(payload, sort_keys=True)}


def _json_attr_value(attribute: object) -> JsonDict:
    if not isinstance(attribute, dict):
        raise ValueError("DynamoDB JSON attribute must be an object.")
    raw_value = attribute.get("S")
    if not isinstance(raw_value, str):
        raise ValueError("DynamoDB JSON attribute must be stored as a string.")
    payload = json.loads(raw_value)
    if not isinstance(payload, dict):
        raise ValueError("DynamoDB JSON attribute must decode to an object.")
    return payload


def _default_dynamodb_client() -> Any:
    import boto3

    return boto3.client("dynamodb")
