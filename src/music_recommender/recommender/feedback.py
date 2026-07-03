from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from music_recommender.models import JsonDict

FeedbackEventType = Literal["like", "dislike", "hide_artist", "save", "skip", "refine"]
_ALLOWED_EVENT_TYPES: set[str] = {"like", "dislike", "hide_artist", "save", "skip", "refine"}


@dataclass(frozen=True)
class FeedbackEvent:
    event_id: str
    session_id: str
    track_id: str
    event_type: str
    metadata: JsonDict
    created_at: str

    def to_dict(self) -> JsonDict:
        return asdict(self)


class JsonFeedbackStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def append(self, event: FeedbackEvent) -> None:
        events = self.list_all()
        events.append(event)
        self._write(events)

    def list_all(self) -> list[FeedbackEvent]:
        if not self.path.exists():
            return []
        payload = json.loads(self.path.read_text())
        if not isinstance(payload, list):
            raise ValueError(f"Feedback store must contain a JSON list: {self.path}")
        return [_event_from_payload(item) for item in payload if isinstance(item, dict)]

    def list_by_session(self, session_id: str) -> list[FeedbackEvent]:
        return [event for event in self.list_all() if event.session_id == session_id]

    def _write(self, events: list[FeedbackEvent]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps([event.to_dict() for event in events], indent=2, sort_keys=True)
        )


class FeedbackService:
    def __init__(self, *, store: JsonFeedbackStore) -> None:
        self.store = store

    def record_feedback(
        self,
        *,
        session_id: str,
        track_id: str,
        event_type: str,
        metadata: JsonDict | None = None,
    ) -> FeedbackEvent:
        if event_type not in _ALLOWED_EVENT_TYPES:
            allowed = ", ".join(sorted(_ALLOWED_EVENT_TYPES))
            raise ValueError(f"Unsupported feedback event_type {event_type!r}; expected {allowed}.")
        event = FeedbackEvent(
            event_id=str(uuid.uuid4()),
            session_id=session_id,
            track_id=track_id,
            event_type=event_type,
            metadata=metadata or {},
            created_at=datetime.now(UTC).isoformat(),
        )
        self.store.append(event)
        return event

    def list_feedback(self, session_id: str) -> list[FeedbackEvent]:
        return self.store.list_by_session(session_id)


def _event_from_payload(payload: dict[str, Any]) -> FeedbackEvent:
    return FeedbackEvent(
        event_id=str(payload["event_id"]),
        session_id=str(payload["session_id"]),
        track_id=str(payload["track_id"]),
        event_type=str(payload["event_type"]),
        metadata=dict(payload.get("metadata") or {}),
        created_at=str(payload["created_at"]),
    )
