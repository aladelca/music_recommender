from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Protocol

from music_recommender.models import JsonDict
from music_recommender.storage.protocols import (
    EvaluationCompletenessRecord,
    FeedbackEventRecord,
    FeedbackEventRepository,
    FeedbackPreferenceRepository,
    MusicEntityRecord,
    ProductFeedbackEventType,
    RecommendationSessionBundle,
    SessionComparison,
    SessionEvaluationRecord,
    SessionEvaluationRepository,
    UserPreferenceRecord,
)


class ProductFeedbackNotFoundError(LookupError):
    pass


class ProductFeedbackConflictError(RuntimeError):
    pass


class ProductFeedbackValidationError(ValueError):
    pass


class FeedbackRecommendationReader(Protocol):
    def get(
        self,
        *,
        account_id: str,
        session_id: str,
    ) -> RecommendationSessionBundle | None: ...


class FeedbackEntityReader(Protocol):
    def get(self, *, mbid: str) -> MusicEntityRecord | None: ...


@dataclass(frozen=True)
class ProductFeedbackResult:
    event: FeedbackEventRecord
    idempotent_replay: bool

    def to_dict(self) -> JsonDict:
        return {
            "event_id": self.event.id,
            "status": "recorded",
            "event_type": self.event.event_type,
            "recording_mbid": self.event.recording_mbid,
            "idempotent_replay": self.idempotent_replay,
        }


class FeedbackEvaluationService:
    def __init__(
        self,
        *,
        recommendations: FeedbackRecommendationReader,
        entities: FeedbackEntityReader,
        feedback: FeedbackEventRepository,
        preferences: FeedbackPreferenceRepository,
        evaluations: SessionEvaluationRepository,
        now: Callable[[], datetime] | None = None,
        event_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.recommendations = recommendations
        self.entities = entities
        self.feedback = feedback
        self.preferences = preferences
        self.evaluations = evaluations
        self.now = now or (lambda: datetime.now(UTC))
        self.event_id_factory = event_id_factory or (lambda: str(uuid.uuid4()))

    def record_feedback(
        self,
        *,
        account_id: str,
        session_id: str,
        recording_mbid: str,
        event_type: ProductFeedbackEventType,
        reason: str | None,
        idempotency_key: str,
    ) -> ProductFeedbackResult:
        normalized_session_id = _uuid(session_id, "Recommendation session ID")
        normalized_recording_mbid = _uuid(recording_mbid, "Recording MBID")
        normalized_key = _text(
            idempotency_key,
            name="Idempotency-Key",
            minimum=1,
            maximum=255,
        )
        if event_type not in {"like", "dislike", "hide_artist", "save", "skip"}:
            raise ProductFeedbackValidationError("Feedback event type is invalid.")
        normalized_reason = (
            _text(reason, name="Feedback reason", minimum=1, maximum=200)
            if reason is not None
            else None
        )
        bundle = self.recommendations.get(
            account_id=account_id,
            session_id=normalized_session_id,
        )
        if bundle is None or normalized_recording_mbid not in {
            item.recording_mbid for item in bundle.items
        }:
            raise ProductFeedbackNotFoundError("Recommendation item was not found.")
        artist_mbids_to_block: tuple[str, ...] = ()
        if event_type == "hide_artist":
            entity = self.entities.get(mbid=normalized_recording_mbid)
            artist_mbids_to_block = (
                tuple(
                    dict.fromkeys(
                        str(credit["mbid"])
                        for credit in entity.artist_credit
                        if isinstance(credit.get("mbid"), str)
                    )
                )
                if entity is not None
                else ()
            )
            if not artist_mbids_to_block:
                raise ProductFeedbackValidationError(
                    "Artist identity is unavailable for this recommendation."
                )
        created_at = _aware_utc(self.now())
        proposed = FeedbackEventRecord(
            id=_uuid(self.event_id_factory(), "Feedback event ID"),
            account_id=account_id,
            session_id=normalized_session_id,
            recording_mbid=normalized_recording_mbid,
            event_type=event_type,
            metadata=({"reason": normalized_reason} if normalized_reason is not None else {}),
            idempotency_key=normalized_key,
            created_at=created_at,
        )
        reservation = self.feedback.create_or_get(proposed)
        stored = reservation.event
        replay = not reservation.created
        if (
            stored.session_id != proposed.session_id
            or stored.recording_mbid != proposed.recording_mbid
            or stored.event_type != proposed.event_type
            or stored.metadata != proposed.metadata
        ):
            raise ProductFeedbackConflictError("Idempotency key already has different feedback.")
        if event_type == "dislike":
            self.preferences.block_recording(
                account_id=account_id,
                recording_mbid=normalized_recording_mbid,
                updated_at=created_at,
            )
        elif event_type == "hide_artist":
            self.preferences.block_artists(
                account_id=account_id,
                artist_mbids=artist_mbids_to_block,
                updated_at=created_at,
            )
        return ProductFeedbackResult(event=stored, idempotent_replay=replay)

    def save_evaluation(
        self,
        *,
        account_id: str,
        session_id: str,
        comparison: SessionComparison,
        explanation_usefulness: int,
        novelty_quality: int,
        comment: str | None,
    ) -> SessionEvaluationRecord:
        normalized_session_id = _uuid(session_id, "Recommendation session ID")
        if (
            self.recommendations.get(
                account_id=account_id,
                session_id=normalized_session_id,
            )
            is None
        ):
            raise ProductFeedbackNotFoundError("Recommendation session was not found.")
        if comparison not in {"better", "same", "worse", "not_sure"}:
            raise ProductFeedbackValidationError("Session comparison is invalid.")
        if not 1 <= explanation_usefulness <= 5 or not 1 <= novelty_quality <= 5:
            raise ProductFeedbackValidationError("Evaluation ratings must be between one and five.")
        normalized_comment = (
            _text(comment, name="Evaluation comment", minimum=1, maximum=1_000)
            if comment is not None
            else None
        )
        now = _aware_utc(self.now())
        return self.evaluations.upsert(
            SessionEvaluationRecord(
                session_id=normalized_session_id,
                account_id=account_id,
                comparison=comparison,
                explanation_usefulness=explanation_usefulness,
                novelty_quality=novelty_quality,
                comment=normalized_comment,
                created_at=now,
                updated_at=now,
            )
        )

    def get_evaluation(
        self,
        *,
        account_id: str,
        session_id: str,
    ) -> SessionEvaluationRecord:
        record = self.evaluations.get(
            account_id=account_id,
            session_id=_uuid(session_id, "Recommendation session ID"),
        )
        if record is None:
            raise ProductFeedbackNotFoundError("Session evaluation was not found.")
        return record

    def get_preferences(self, *, account_id: str) -> JsonDict:
        return self._preference_payload(self.preferences.get(account_id=account_id))

    def unblock_artist(self, *, account_id: str, artist_mbid: str) -> JsonDict:
        normalized_mbid = _uuid(artist_mbid, "Artist MBID")
        current = self.preferences.get(account_id=account_id)
        if current is None or normalized_mbid not in current.blocked_artist_mbids:
            return self._preference_payload(current)
        updated = self.preferences.unblock_artist(
            account_id=account_id,
            artist_mbid=normalized_mbid,
            updated_at=_aware_utc(self.now()),
        )
        return self._preference_payload(updated)

    def _preference_payload(self, record: UserPreferenceRecord | None) -> JsonDict:
        if record is None:
            return {
                "allow_explicit": True,
                "blocked_artists": [],
                "blocked_recordings": [],
            }
        return {
            "allow_explicit": record.allow_explicit,
            "blocked_artists": [
                {
                    "mbid": mbid,
                    "name": self._entity_name(mbid, fallback="MusicBrainz artist"),
                }
                for mbid in record.blocked_artist_mbids
            ],
            "blocked_recordings": [
                {
                    "mbid": mbid,
                    "name": self._entity_name(mbid, fallback="MusicBrainz recording"),
                }
                for mbid in record.blocked_recording_mbids
            ],
        }

    def _entity_name(self, mbid: str, *, fallback: str) -> str:
        entity = self.entities.get(mbid=mbid)
        return entity.name if entity is not None and entity.name != mbid else fallback

    def evaluation_completeness(self) -> EvaluationCompletenessRecord:
        return self.evaluations.completeness()


def evaluation_payload(record: SessionEvaluationRecord) -> JsonDict:
    return {
        "session_id": record.session_id,
        "comparison": record.comparison,
        "explanation_usefulness": record.explanation_usefulness,
        "novelty_quality": record.novelty_quality,
        "comment": record.comment,
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
    }


def evaluation_completeness_payload(record: EvaluationCompletenessRecord) -> JsonDict:
    return asdict(record)


def _uuid(value: str, name: str) -> str:
    try:
        return str(uuid.UUID(value))
    except ValueError:
        raise ProductFeedbackValidationError(f"{name} is invalid.") from None


def _text(value: str, *, name: str, minimum: int, maximum: int) -> str:
    normalized = " ".join(value.split())
    if not minimum <= len(normalized) <= maximum or any(
        ord(character) < 32 for character in normalized
    ):
        raise ProductFeedbackValidationError(
            f"{name} must contain between {minimum} and {maximum} characters."
        )
    return normalized


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Feedback timestamps must be timezone-aware.")
    return value.astimezone(UTC)
