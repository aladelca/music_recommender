from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Protocol

AccessStatus = Literal["pending", "approved", "revoked"]
MusicEntityType = Literal["artist", "recording"]
MusicEntitySource = Literal["musicbrainz", "listenbrainz"]
SourceCacheStatus = Literal["fresh", "negative", "error"]
DiscoveryJobStatus = Literal["queued", "running", "ready", "degraded", "failed"]
CompletedDiscoveryJobStatus = Literal["ready", "degraded", "failed"]
RecommendationStatus = Literal[
    "queued",
    "ready",
    "degraded",
    "insufficient",
    "reviewed",
    "exported",
    "failed",
]
PlaylistExportStatus = Literal[
    "creating",
    "adding_items",
    "complete",
    "partial_failure",
    "failed",
]
ProductFeedbackEventType = Literal["like", "dislike", "hide_artist", "save", "skip"]
SessionComparison = Literal["better", "same", "worse", "not_sure"]
CandidateSourceAdapter = Literal[
    "listenbrainz_artist_radio",
    "listenbrainz_tag_radio",
    "listenbrainz_labs_similarity",
]
ExternalIdProvider = Literal["spotify"]


class ApprovedUserLimitError(RuntimeError):
    pass


@dataclass(frozen=True)
class UserAccountRecord:
    account_id: str
    display_name: str | None
    access_status: AccessStatus
    refresh_token_ciphertext: bytes | None
    token_scopes: tuple[str, ...]
    token_issued_at: datetime | None
    reauthorization_required: bool
    last_login_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class OAuthStateRecord:
    state_hash: str
    verifier_ciphertext: bytes
    return_path: str
    expires_at: datetime
    created_at: datetime


@dataclass(frozen=True)
class ApplicationSessionRecord:
    session_hash: str
    account_id: str
    csrf_hash: str
    idle_expires_at: datetime
    absolute_expires_at: datetime
    last_seen_at: datetime
    created_at: datetime
    revoked_at: datetime | None = None


@dataclass(frozen=True)
class BetaAccountRecord:
    account_id: str
    access_status: AccessStatus
    last_login_at: datetime | None


@dataclass(frozen=True)
class MusicEntityRecord:
    mbid: str
    entity_type: MusicEntityType
    name: str
    artist_credit: tuple[dict[str, Any], ...]
    release_data: dict[str, Any]
    isrcs: tuple[str, ...]
    source: MusicEntitySource
    source_version: str | None
    fetched_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class UserSeedInput:
    entity_type: MusicEntityType
    mbid: str
    display_name: str


@dataclass(frozen=True)
class UserSeedRecord:
    id: str
    account_id: str
    entity_type: MusicEntityType
    mbid: str
    display_name: str
    position: int
    selected_at: datetime


@dataclass(frozen=True)
class SourceCacheRecord:
    source: Literal["musicbrainz", "listenbrainz", "listenbrainz_labs"]
    cache_key: str
    status: SourceCacheStatus
    normalized_payload: dict[str, Any]
    etag: str | None
    fetched_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class DiscoveryJobRecord:
    id: str
    account_id: str
    request_fingerprint: str
    status: DiscoveryJobStatus
    source_adapters: tuple[str, ...]
    attempt_count: int
    error_code: str | None
    queued_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


@dataclass(frozen=True)
class CandidateEdgeRecord:
    seed_mbid: str
    candidate_recording_mbid: str
    source_adapter: CandidateSourceAdapter
    algorithm_version: str
    strength: float | None
    listener_count: int | None
    source_facts: dict[str, Any]
    fetched_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class ExternalIdMappingRecord:
    recording_mbid: str
    provider: ExternalIdProvider
    provider_id: str
    mapping_source: str
    confidence: float | None
    fetched_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class UserPreferenceRecord:
    account_id: str
    blocked_artist_mbids: tuple[str, ...]
    blocked_recording_mbids: tuple[str, ...]
    allow_explicit: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class RecommendationSessionRecord:
    id: str
    account_id: str
    prompt: str
    controls: dict[str, Any]
    parsed_intent: dict[str, Any]
    seed_ids: tuple[str, ...]
    source_snapshot: dict[str, Any]
    ranking_version: str
    status: RecommendationStatus
    generated_at: datetime
    updated_at: datetime
    reviewed_playlist_name: str | None
    reviewed_playlist_public: bool | None


@dataclass(frozen=True)
class RecommendationItemRecord:
    session_id: str
    recording_mbid: str
    spotify_track_id: str | None
    original_rank: int
    internal_score_components: dict[str, Any]
    evidence: dict[str, Any]
    display_snapshot: dict[str, Any]
    selected: bool
    reviewed_order: int | None
    created_at: datetime


@dataclass(frozen=True)
class RecommendationSessionBundle:
    session: RecommendationSessionRecord
    items: tuple[RecommendationItemRecord, ...]


@dataclass(frozen=True)
class PlaylistExportRecord:
    id: str
    session_id: str
    account_id: str
    spotify_playlist_id: str | None
    spotify_playlist_url: str | None
    name: str
    description: str
    public: bool
    recording_mbids: tuple[str, ...]
    spotify_track_ids: tuple[str, ...]
    request_fingerprint: str
    idempotency_key: str
    status: PlaylistExportStatus
    tracks_added: int
    partial_failure: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class PlaylistExportReservation:
    record: PlaylistExportRecord
    created: bool


@dataclass(frozen=True)
class FeedbackEventRecord:
    id: str
    account_id: str
    session_id: str
    recording_mbid: str
    event_type: ProductFeedbackEventType
    metadata: dict[str, Any]
    idempotency_key: str
    created_at: datetime


@dataclass(frozen=True)
class FeedbackEventReservation:
    event: FeedbackEventRecord
    created: bool


@dataclass(frozen=True)
class SessionEvaluationRecord:
    session_id: str
    account_id: str
    comparison: SessionComparison
    explanation_usefulness: int
    novelty_quality: int
    comment: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class EvaluationCompletenessRecord:
    approved_accounts: int
    eligible_sessions: int
    completed_evaluations: int
    accounts_with_evaluation: int


@dataclass(frozen=True)
class CleanupResult:
    oauth_states: int
    application_sessions: int
    source_cache_entries: int
    candidate_edges: int
    external_id_mappings: int
    discovery_jobs: int
    recommendation_sessions: int
    removed_user_seeds: int
    music_entities: int

    def to_dict(self) -> dict[str, int]:
        return {
            "oauth_states": self.oauth_states,
            "application_sessions": self.application_sessions,
            "source_cache_entries": self.source_cache_entries,
            "candidate_edges": self.candidate_edges,
            "external_id_mappings": self.external_id_mappings,
            "discovery_jobs": self.discovery_jobs,
            "recommendation_sessions": self.recommendation_sessions,
            "removed_user_seeds": self.removed_user_seeds,
            "music_entities": self.music_entities,
        }


class UserRepository(Protocol):
    def get(self, *, account_id: str) -> UserAccountRecord | None: ...

    def upsert_pending(
        self,
        *,
        account_id: str,
        display_name: str | None,
        refresh_token_ciphertext: bytes,
        token_scopes: tuple[str, ...],
        token_issued_at: datetime,
        login_at: datetime,
    ) -> UserAccountRecord: ...

    def set_access_status(
        self,
        *,
        account_id: str,
        status: AccessStatus,
    ) -> UserAccountRecord: ...

    def replace_refresh_token(
        self,
        *,
        account_id: str,
        refresh_token_ciphertext: bytes,
        token_scopes: tuple[str, ...],
        token_issued_at: datetime,
    ) -> UserAccountRecord: ...


class OAuthStateRepository(Protocol):
    def put(self, state: OAuthStateRecord) -> None: ...

    def consume(self, *, state_hash: str, now: datetime) -> OAuthStateRecord | None: ...


class ApplicationSessionRepository(Protocol):
    def put(self, session: ApplicationSessionRecord) -> None: ...

    def get_active(
        self,
        *,
        session_hash: str,
        now: datetime,
    ) -> ApplicationSessionRecord | None: ...

    def touch(
        self,
        *,
        session_hash: str,
        account_id: str,
        last_seen_at: datetime,
        idle_expires_at: datetime,
    ) -> ApplicationSessionRecord | None: ...

    def revoke(
        self,
        *,
        session_hash: str,
        account_id: str,
        revoked_at: datetime,
    ) -> bool: ...


class BetaAccessRepository(Protocol):
    def list_pending(self) -> tuple[BetaAccountRecord, ...]: ...

    def get(self, *, account_id: str) -> BetaAccountRecord | None: ...

    def approved_count(self) -> int: ...

    def approve(self, *, account_id: str, changed_at: datetime) -> BetaAccountRecord: ...

    def revoke(self, *, account_id: str, changed_at: datetime) -> BetaAccountRecord: ...


class MusicEntityRepository(Protocol):
    def upsert(self, entity: MusicEntityRecord) -> MusicEntityRecord: ...

    def get(self, *, mbid: str) -> MusicEntityRecord | None: ...


class UserSeedRepository(Protocol):
    def replace_active(
        self,
        *,
        account_id: str,
        seeds: tuple[UserSeedInput, ...],
        selected_at: datetime,
    ) -> tuple[UserSeedRecord, ...]: ...

    def list_active(self, *, account_id: str) -> tuple[UserSeedRecord, ...]: ...


class SourceCacheRepository(Protocol):
    def put(self, record: SourceCacheRecord) -> SourceCacheRecord: ...

    def get_fresh(
        self,
        *,
        source: str,
        cache_key: str,
        now: datetime,
    ) -> SourceCacheRecord | None: ...


class SourceRateLimitRepository(Protocol):
    def reserve(
        self,
        *,
        source: str,
        now: datetime,
        minimum_interval_seconds: float,
    ) -> datetime: ...

    def defer(self, *, source: str, not_before: datetime) -> datetime: ...


class DiscoveryJobRepository(Protocol):
    def create_or_get(
        self,
        *,
        account_id: str,
        request_fingerprint: str,
        source_adapters: tuple[str, ...],
        queued_at: datetime,
    ) -> DiscoveryJobRecord: ...

    def get(self, *, account_id: str, job_id: str) -> DiscoveryJobRecord | None: ...

    def claim(
        self,
        *,
        account_id: str,
        job_id: str,
        started_at: datetime,
        reclaim_started_before: datetime,
    ) -> DiscoveryJobRecord | None: ...

    def release_for_retry(
        self,
        *,
        account_id: str,
        job_id: str,
        error_code: str,
    ) -> DiscoveryJobRecord: ...

    def complete(
        self,
        *,
        account_id: str,
        job_id: str,
        status: CompletedDiscoveryJobStatus,
        error_code: str | None,
        completed_at: datetime,
    ) -> DiscoveryJobRecord: ...


class CandidateEdgeRepository(Protocol):
    def upsert(self, edge: CandidateEdgeRecord) -> CandidateEdgeRecord: ...

    def list_fresh(
        self,
        *,
        seed_mbids: tuple[str, ...],
        now: datetime,
    ) -> tuple[CandidateEdgeRecord, ...]: ...


class ExternalIdMappingRepository(Protocol):
    def upsert(self, record: ExternalIdMappingRecord) -> ExternalIdMappingRecord: ...

    def get_fresh(
        self,
        *,
        recording_mbid: str,
        provider: ExternalIdProvider,
        now: datetime,
    ) -> ExternalIdMappingRecord | None: ...


class UserPreferenceRepository(Protocol):
    def get(self, *, account_id: str) -> UserPreferenceRecord | None: ...


class RecommendationRepository(Protocol):
    def create_with_items(
        self,
        *,
        session: RecommendationSessionRecord,
        items: tuple[RecommendationItemRecord, ...],
    ) -> RecommendationSessionBundle: ...

    def get(
        self,
        *,
        account_id: str,
        session_id: str,
    ) -> RecommendationSessionBundle | None: ...

    def list_sessions(
        self,
        *,
        account_id: str,
        limit: int,
        before_generated_at: datetime | None,
        before_id: str | None,
    ) -> tuple[RecommendationSessionRecord, ...]: ...

    def replace_selection(
        self,
        *,
        account_id: str,
        session_id: str,
        recording_mbids: tuple[str, ...],
        playlist_name: str,
        playlist_public: bool,
        reviewed_at: datetime,
    ) -> RecommendationSessionBundle | None: ...


class PlaylistExportRepository(Protocol):
    def create_or_get(self, record: PlaylistExportRecord) -> PlaylistExportReservation: ...

    def set_playlist_created(
        self,
        *,
        account_id: str,
        export_id: str,
        spotify_playlist_id: str,
        spotify_playlist_url: str | None,
        updated_at: datetime,
    ) -> PlaylistExportRecord: ...

    def mark_complete(
        self,
        *,
        account_id: str,
        export_id: str,
        tracks_added: int,
        updated_at: datetime,
    ) -> PlaylistExportRecord: ...

    def mark_partial_failure(
        self,
        *,
        account_id: str,
        export_id: str,
        error_code: str,
        updated_at: datetime,
    ) -> PlaylistExportRecord: ...


class FeedbackEventRepository(Protocol):
    def create_or_get(self, record: FeedbackEventRecord) -> FeedbackEventReservation: ...


class FeedbackPreferenceRepository(Protocol):
    def get(self, *, account_id: str) -> UserPreferenceRecord | None: ...

    def block_recording(
        self,
        *,
        account_id: str,
        recording_mbid: str,
        updated_at: datetime,
    ) -> UserPreferenceRecord: ...

    def block_artists(
        self,
        *,
        account_id: str,
        artist_mbids: tuple[str, ...],
        updated_at: datetime,
    ) -> UserPreferenceRecord: ...

    def unblock_artist(
        self,
        *,
        account_id: str,
        artist_mbid: str,
        updated_at: datetime,
    ) -> UserPreferenceRecord: ...


class SessionEvaluationRepository(Protocol):
    def upsert(self, record: SessionEvaluationRecord) -> SessionEvaluationRecord: ...

    def get(
        self,
        *,
        account_id: str,
        session_id: str,
    ) -> SessionEvaluationRecord | None: ...

    def completeness(self) -> EvaluationCompletenessRecord: ...


class AccountDeletionRepository(Protocol):
    def hard_delete(self, *, account_id: str) -> bool: ...


class CleanupRepository(Protocol):
    def cleanup(self, *, now: datetime, batch_size: int) -> CleanupResult: ...
