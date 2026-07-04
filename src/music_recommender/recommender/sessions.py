from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from music_recommender.models import JsonDict


@dataclass(frozen=True)
class PlaylistResult:
    playlist_id: str
    url: str | None
    requested_track_ids: tuple[str, ...]
    tracks_added: tuple[str, ...]
    snapshot_id: str | None
    idempotent_replay: bool
    partial_failures: tuple[str, ...] = ()

    def to_dict(self) -> JsonDict:
        payload = asdict(self)
        payload["requested_track_ids"] = list(self.requested_track_ids)
        payload["tracks_added"] = list(self.tracks_added)
        payload["partial_failures"] = list(self.partial_failures)
        return payload


@dataclass(frozen=True)
class RecommendationSession:
    session_id: str
    user_id: str
    prompt: str
    intent: JsonDict
    recommended_track_ids: tuple[str, ...]
    recommendations: tuple[JsonDict, ...]
    catalog_run_id: str | None
    interaction_run_id: str | None
    playlist_candidate: JsonDict | None
    created_at: str
    updated_at: str
    playlist_result: PlaylistResult | None = None

    def invalid_track_ids(self, requested_track_ids: tuple[str, ...]) -> tuple[str, ...]:
        allowed = set(self.recommended_track_ids)
        return tuple(track_id for track_id in requested_track_ids if track_id not in allowed)

    def with_playlist_result(self, playlist_result: PlaylistResult) -> RecommendationSession:
        return RecommendationSession(
            session_id=self.session_id,
            user_id=self.user_id,
            prompt=self.prompt,
            intent=self.intent,
            recommended_track_ids=self.recommended_track_ids,
            recommendations=self.recommendations,
            catalog_run_id=self.catalog_run_id,
            interaction_run_id=self.interaction_run_id,
            playlist_candidate=self.playlist_candidate,
            created_at=self.created_at,
            updated_at=datetime.now(UTC).isoformat(),
            playlist_result=playlist_result,
        )

    def to_dict(self) -> JsonDict:
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "prompt": self.prompt,
            "intent": self.intent,
            "recommended_track_ids": list(self.recommended_track_ids),
            "recommendations": list(self.recommendations),
            "catalog_run_id": self.catalog_run_id,
            "interaction_run_id": self.interaction_run_id,
            "playlist_candidate": self.playlist_candidate,
            "playlist_result": (
                self.playlist_result.to_dict() if self.playlist_result is not None else None
            ),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class RecommendationSessionStore(Protocol):
    def get(self, session_id: str) -> RecommendationSession | None: ...

    def put(self, session: RecommendationSession) -> None: ...

    def update_playlist_result(
        self,
        session_id: str,
        playlist_result: PlaylistResult,
    ) -> RecommendationSession: ...


class JsonRecommendationSessionStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def get(self, session_id: str) -> RecommendationSession | None:
        return self._load().get(session_id)

    def put(self, session: RecommendationSession) -> None:
        sessions = self._load()
        sessions[session.session_id] = session
        self._write(sessions)

    def update_playlist_result(
        self,
        session_id: str,
        playlist_result: PlaylistResult,
    ) -> RecommendationSession:
        sessions = self._load()
        session = sessions[session_id]
        updated = session.with_playlist_result(playlist_result)
        sessions[session_id] = updated
        self._write(sessions)
        return updated

    def _load(self) -> dict[str, RecommendationSession]:
        if not self.path.exists():
            return {}
        payload = json.loads(self.path.read_text())
        if not isinstance(payload, dict):
            raise ValueError(f"Session store must contain a JSON object: {self.path}")
        return {
            str(session_id): _session_from_payload(session)
            for session_id, session in payload.items()
            if isinstance(session, dict)
        }

    def _write(self, sessions: dict[str, RecommendationSession]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(
                {session_id: session.to_dict() for session_id, session in sessions.items()},
                indent=2,
                sort_keys=True,
            )
        )


def _session_from_payload(payload: dict[str, Any]) -> RecommendationSession:
    playlist_result = payload.get("playlist_result")
    return RecommendationSession(
        session_id=str(payload["session_id"]),
        user_id=str(payload["user_id"]),
        prompt=str(payload["prompt"]),
        intent=dict(payload.get("intent") or {}),
        recommended_track_ids=tuple(str(item) for item in payload.get("recommended_track_ids", [])),
        recommendations=tuple(
            dict(item) for item in payload.get("recommendations", []) if isinstance(item, dict)
        ),
        catalog_run_id=_optional_str(payload.get("catalog_run_id")),
        interaction_run_id=_optional_str(payload.get("interaction_run_id")),
        playlist_candidate=(
            dict(payload["playlist_candidate"])
            if isinstance(payload.get("playlist_candidate"), dict)
            else None
        ),
        playlist_result=(
            _playlist_result_from_payload(playlist_result)
            if isinstance(playlist_result, dict)
            else None
        ),
        created_at=str(payload["created_at"]),
        updated_at=str(payload["updated_at"]),
    )


def _playlist_result_from_payload(payload: dict[str, Any]) -> PlaylistResult:
    return PlaylistResult(
        playlist_id=str(payload["playlist_id"]),
        url=_optional_str(payload.get("url")),
        requested_track_ids=tuple(str(item) for item in payload.get("requested_track_ids", [])),
        tracks_added=tuple(str(item) for item in payload.get("tracks_added", [])),
        snapshot_id=_optional_str(payload.get("snapshot_id")),
        idempotent_replay=bool(payload.get("idempotent_replay", False)),
        partial_failures=tuple(str(item) for item in payload.get("partial_failures", [])),
    )


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
