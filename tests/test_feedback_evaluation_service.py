from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from music_recommender.product.feedback_service import (
    FeedbackEvaluationService,
    ProductFeedbackConflictError,
    ProductFeedbackNotFoundError,
)
from music_recommender.storage.protocols import (
    EvaluationCompletenessRecord,
    FeedbackEventRecord,
    FeedbackEventReservation,
    MusicEntityRecord,
    RecommendationItemRecord,
    RecommendationSessionBundle,
    RecommendationSessionRecord,
    SessionEvaluationRecord,
    UserPreferenceRecord,
)

SESSION_ID = "40000000-0000-0000-0000-000000000001"
RECORDING = "30000000-0000-0000-0000-000000000001"
ARTIST = "20000000-0000-0000-0000-000000000001"


class FakeRecommendations:
    def __init__(self, bundle: RecommendationSessionBundle) -> None:
        self.bundle = bundle

    def get(self, *, account_id: str, session_id: str) -> RecommendationSessionBundle | None:
        if account_id == self.bundle.session.account_id and session_id == self.bundle.session.id:
            return self.bundle
        return None


class FakeEntities:
    def __init__(self, entity: MusicEntityRecord) -> None:
        self.entity = entity

    def get(self, *, mbid: str) -> MusicEntityRecord | None:
        return self.entity if mbid == self.entity.mbid else None


class InMemoryFeedback:
    def __init__(self) -> None:
        self.records: dict[tuple[str, str], FeedbackEventRecord] = {}

    def create_or_get(self, record: FeedbackEventRecord) -> FeedbackEventReservation:
        key = (record.account_id, record.idempotency_key)
        existing = self.records.get(key)
        if existing is not None:
            return FeedbackEventReservation(event=existing, created=False)
        self.records[key] = record
        return FeedbackEventReservation(event=record, created=True)


class InMemoryPreferences:
    def __init__(self, now: datetime) -> None:
        self.records: dict[str, UserPreferenceRecord] = {}
        self.now = now

    def block_recording(self, **kwargs: Any) -> UserPreferenceRecord:
        current = self._get(kwargs["account_id"])
        updated = replace(
            current,
            blocked_recording_mbids=tuple(
                sorted(set(current.blocked_recording_mbids) | {kwargs["recording_mbid"]})
            ),
            updated_at=kwargs["updated_at"],
        )
        self.records[current.account_id] = updated
        return updated

    def block_artists(self, **kwargs: Any) -> UserPreferenceRecord:
        current = self._get(kwargs["account_id"])
        updated = replace(
            current,
            blocked_artist_mbids=tuple(
                sorted(set(current.blocked_artist_mbids) | set(kwargs["artist_mbids"]))
            ),
            updated_at=kwargs["updated_at"],
        )
        self.records[current.account_id] = updated
        return updated

    def get(self, *, account_id: str) -> UserPreferenceRecord | None:
        return self.records.get(account_id)

    def unblock_artist(self, **kwargs: Any) -> UserPreferenceRecord:
        current = self._get(kwargs["account_id"])
        updated = replace(
            current,
            blocked_artist_mbids=tuple(
                mbid for mbid in current.blocked_artist_mbids if mbid != kwargs["artist_mbid"]
            ),
            updated_at=kwargs["updated_at"],
        )
        self.records[current.account_id] = updated
        return updated

    def _get(self, account_id: str) -> UserPreferenceRecord:
        return self.records.get(
            account_id,
            UserPreferenceRecord(
                account_id=account_id,
                blocked_artist_mbids=(),
                blocked_recording_mbids=(),
                allow_explicit=False,
                created_at=self.now,
                updated_at=self.now,
            ),
        )


class InMemoryEvaluations:
    def __init__(self) -> None:
        self.records: dict[str, SessionEvaluationRecord] = {}

    def upsert(self, record: SessionEvaluationRecord) -> SessionEvaluationRecord:
        existing = self.records.get(record.session_id)
        if existing is not None:
            record = replace(record, created_at=existing.created_at)
        self.records[record.session_id] = record
        return record

    def get(self, *, account_id: str, session_id: str) -> SessionEvaluationRecord | None:
        record = self.records.get(session_id)
        return record if record and record.account_id == account_id else None

    def completeness(self) -> EvaluationCompletenessRecord:
        return EvaluationCompletenessRecord(
            approved_accounts=5,
            eligible_sessions=3,
            completed_evaluations=len(self.records),
            accounts_with_evaluation=1 if self.records else 0,
        )


def test_feedback_is_item_owned_idempotent_and_updates_only_account_preferences() -> None:
    service, feedback, preferences, _ = build_service()

    first = service.record_feedback(
        account_id="account-1",
        session_id=SESSION_ID,
        recording_mbid=RECORDING,
        event_type="dislike",
        reason="Not for me",
        idempotency_key="feedback-key-1",
    )
    replay = service.record_feedback(
        account_id="account-1",
        session_id=SESSION_ID,
        recording_mbid=RECORDING,
        event_type="dislike",
        reason="Not for me",
        idempotency_key="feedback-key-1",
    )

    assert first.idempotent_replay is False
    assert replay.idempotent_replay is True
    assert len(feedback.records) == 1
    assert preferences.records["account-1"].blocked_recording_mbids == (RECORDING,)
    assert "account-2" not in preferences.records


def test_hide_artist_uses_independent_artist_mbid_and_conflicts_are_rejected() -> None:
    service, _, preferences, _ = build_service()

    service.record_feedback(
        account_id="account-1",
        session_id=SESSION_ID,
        recording_mbid=RECORDING,
        event_type="hide_artist",
        reason=None,
        idempotency_key="feedback-key-2",
    )
    with pytest.raises(ProductFeedbackConflictError):
        service.record_feedback(
            account_id="account-1",
            session_id=SESSION_ID,
            recording_mbid=RECORDING,
            event_type="like",
            reason=None,
            idempotency_key="feedback-key-2",
        )

    assert preferences.records["account-1"].blocked_artist_mbids == (ARTIST,)


def test_feedback_rejects_cross_account_or_unowned_items_before_write() -> None:
    service, feedback, _, _ = build_service()

    with pytest.raises(ProductFeedbackNotFoundError):
        service.record_feedback(
            account_id="account-2",
            session_id=SESSION_ID,
            recording_mbid=RECORDING,
            event_type="like",
            reason=None,
            idempotency_key="feedback-key-3",
        )

    assert feedback.records == {}


def test_preferences_can_be_listed_and_artist_blocks_removed_for_current_account() -> None:
    service, _, preferences, _ = build_service()
    service.record_feedback(
        account_id="account-1",
        session_id=SESSION_ID,
        recording_mbid=RECORDING,
        event_type="hide_artist",
        reason=None,
        idempotency_key="feedback-key-preferences",
    )

    listed = service.get_preferences(account_id="account-1")
    removed = service.unblock_artist(account_id="account-1", artist_mbid=ARTIST)

    assert listed["blocked_artists"] == [{"mbid": ARTIST, "name": "MusicBrainz artist"}]
    assert removed["blocked_artists"] == []
    assert preferences.records["account-1"].blocked_artist_mbids == ()


def test_session_evaluation_is_account_scoped_updatable_and_reports_aggregate_completion() -> None:
    service, _, _, evaluations = build_service()

    created = service.save_evaluation(
        account_id="account-1",
        session_id=SESSION_ID,
        comparison="better",
        explanation_usefulness=5,
        novelty_quality=4,
        comment="The evidence was useful.",
    )
    updated = service.save_evaluation(
        account_id="account-1",
        session_id=SESSION_ID,
        comparison="same",
        explanation_usefulness=4,
        novelty_quality=3,
        comment=None,
    )

    assert updated.created_at == created.created_at
    assert (
        service.get_evaluation(
            account_id="account-1",
            session_id=SESSION_ID,
        )
        == updated
    )
    assert service.evaluation_completeness() == EvaluationCompletenessRecord(
        approved_accounts=5,
        eligible_sessions=3,
        completed_evaluations=1,
        accounts_with_evaluation=1,
    )
    with pytest.raises(ProductFeedbackNotFoundError):
        service.get_evaluation(account_id="account-2", session_id=SESSION_ID)


def build_service() -> tuple[
    FeedbackEvaluationService,
    InMemoryFeedback,
    InMemoryPreferences,
    InMemoryEvaluations,
]:
    now = datetime(2030, 1, 1, tzinfo=UTC)
    feedback = InMemoryFeedback()
    preferences = InMemoryPreferences(now)
    evaluations = InMemoryEvaluations()
    return (
        FeedbackEvaluationService(
            recommendations=FakeRecommendations(bundle(now)),
            entities=FakeEntities(entity(now)),
            feedback=feedback,
            preferences=preferences,
            evaluations=evaluations,
            now=lambda: now,
            event_id_factory=lambda: "60000000-0000-0000-0000-000000000001",
        ),
        feedback,
        preferences,
        evaluations,
    )


def bundle(now: datetime) -> RecommendationSessionBundle:
    return RecommendationSessionBundle(
        session=RecommendationSessionRecord(
            id=SESSION_ID,
            account_id="account-1",
            prompt="Outside my loop",
            controls={},
            parsed_intent={},
            seed_ids=("00000000-0000-0000-0000-000000000001",),
            source_snapshot={},
            ranking_version="explicit-discovery-v1",
            status="ready",
            generated_at=now,
            updated_at=now,
            reviewed_playlist_name=None,
            reviewed_playlist_public=None,
        ),
        items=(
            RecommendationItemRecord(
                session_id=SESSION_ID,
                recording_mbid=RECORDING,
                spotify_track_id="spotify-1",
                original_rank=1,
                internal_score_components={},
                evidence={},
                display_snapshot={},
                selected=True,
                reviewed_order=None,
                created_at=now,
            ),
        ),
    )


def entity(now: datetime) -> MusicEntityRecord:
    return MusicEntityRecord(
        mbid=RECORDING,
        entity_type="recording",
        name="Roads",
        artist_credit=({"mbid": ARTIST, "name": "Portishead"},),
        release_data={},
        isrcs=(),
        source="listenbrainz",
        source_version="lb-core-v1",
        fetched_at=now,
        expires_at=now,
    )
