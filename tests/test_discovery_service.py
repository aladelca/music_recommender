from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from music_recommender.observability import ProductObserver
from music_recommender.product.discovery_service import (
    DiscoveryJobService,
    DiscoveryRetryableError,
    DiscoveryWorker,
)
from music_recommender.sources.listenbrainz_api import (
    ListenBrainzCandidate,
    ListenBrainzCandidateBatch,
    ListenBrainzMetadataBatch,
    ListenBrainzRecordingMetadata,
    ListenBrainzUnavailableError,
)
from music_recommender.storage.protocols import (
    CandidateEdgeRecord,
    DiscoveryJobRecord,
    MusicEntityRecord,
    SourceCacheRecord,
    UserSeedRecord,
)


class InMemoryJobRepository:
    def __init__(self) -> None:
        self.records: dict[str, DiscoveryJobRecord] = {}

    def create_or_get(self, **kwargs: Any) -> DiscoveryJobRecord:
        for record in self.records.values():
            if (
                record.account_id == kwargs["account_id"]
                and record.request_fingerprint == kwargs["request_fingerprint"]
                and record.status in {"queued", "running"}
            ):
                return record
        job_id = f"job-{len(self.records) + 1}"
        record = DiscoveryJobRecord(
            id=job_id,
            account_id=kwargs["account_id"],
            request_fingerprint=kwargs["request_fingerprint"],
            status="queued",
            source_adapters=kwargs["source_adapters"],
            attempt_count=0,
            error_code=None,
            queued_at=kwargs["queued_at"],
            started_at=None,
            completed_at=None,
        )
        self.records[job_id] = record
        return record

    def get(self, *, account_id: str, job_id: str) -> DiscoveryJobRecord | None:
        record = self.records.get(job_id)
        return record if record and record.account_id == account_id else None

    def claim(self, **kwargs: Any) -> DiscoveryJobRecord | None:
        record = self.get(account_id=kwargs["account_id"], job_id=kwargs["job_id"])
        can_reclaim = (
            record is not None
            and record.status == "running"
            and record.started_at is not None
            and record.started_at <= kwargs["reclaim_started_before"]
        )
        if record is None or (record.status != "queued" and not can_reclaim):
            return None
        claimed = replace(
            record,
            status="running",
            attempt_count=record.attempt_count + 1,
            started_at=kwargs["started_at"],
        )
        self.records[record.id] = claimed
        return claimed

    def complete(self, **kwargs: Any) -> DiscoveryJobRecord:
        record = self.records[kwargs["job_id"]]
        completed = replace(
            record,
            status=kwargs["status"],
            error_code=kwargs["error_code"],
            completed_at=kwargs["completed_at"],
        )
        self.records[record.id] = completed
        return completed

    def release_for_retry(self, **kwargs: Any) -> DiscoveryJobRecord:
        record = self.records[kwargs["job_id"]]
        queued = replace(
            record,
            status="queued",
            error_code=kwargs["error_code"],
            started_at=None,
        )
        self.records[record.id] = queued
        return queued


class InMemorySeedRepository:
    def __init__(self, seeds: tuple[UserSeedRecord, ...]) -> None:
        self.seeds = seeds

    def list_active(self, *, account_id: str) -> tuple[UserSeedRecord, ...]:
        return tuple(seed for seed in self.seeds if seed.account_id == account_id)


class InMemoryEntityRepository:
    def __init__(self, entities: tuple[MusicEntityRecord, ...]) -> None:
        self.records = {entity.mbid: entity for entity in entities}

    def upsert(self, entity: MusicEntityRecord) -> MusicEntityRecord:
        self.records[entity.mbid] = entity
        return entity

    def get(self, *, mbid: str) -> MusicEntityRecord | None:
        return self.records.get(mbid)


class ExplodingEntityRepository(InMemoryEntityRepository):
    def get(self, *, mbid: str) -> MusicEntityRecord | None:
        del mbid
        raise RuntimeError("unexpected entity repository failure")


class InMemoryCacheRepository:
    def __init__(self) -> None:
        self.records: dict[tuple[str, str], SourceCacheRecord] = {}

    def put(self, record: SourceCacheRecord) -> SourceCacheRecord:
        self.records[(record.source, record.cache_key)] = record
        return record

    def get_fresh(self, **kwargs: Any) -> SourceCacheRecord | None:
        record = self.records.get((kwargs["source"], kwargs["cache_key"]))
        return record if record and record.expires_at > kwargs["now"] else None


class InMemoryCandidateRepository:
    def __init__(self) -> None:
        self.records: dict[tuple[str, str, str, str], CandidateEdgeRecord] = {}

    def upsert(self, edge: CandidateEdgeRecord) -> CandidateEdgeRecord:
        key = (
            edge.seed_mbid,
            edge.candidate_recording_mbid,
            edge.source_adapter,
            edge.algorithm_version,
        )
        self.records[key] = edge
        return edge

    def list_fresh(self, **kwargs: Any) -> tuple[CandidateEdgeRecord, ...]:
        return tuple(
            edge
            for edge in self.records.values()
            if edge.seed_mbid in kwargs["seed_mbids"] and edge.expires_at > kwargs["now"]
        )


class FakeRateLimiter:
    def __init__(self) -> None:
        self.reservations: list[str] = []
        self.deferrals: list[datetime] = []

    def reserve(
        self,
        *,
        source: str,
        now: datetime,
        minimum_interval_seconds: float,
    ) -> datetime:
        del minimum_interval_seconds
        self.reservations.append(source)
        return now

    def defer(self, *, source: str, not_before: datetime) -> datetime:
        assert source == "listenbrainz"
        self.deferrals.append(not_before)
        return not_before


class FakePublisher:
    def __init__(self) -> None:
        self.messages: list[dict[str, str]] = []

    def publish(self, **kwargs: str) -> None:
        self.messages.append(kwargs)


class FakeListenBrainz:
    def __init__(self) -> None:
        self.artist_calls = 0
        self.tag_calls = 0
        self.metadata_calls = 0

    def artist_radio(self, artist_mbid: str, **kwargs: Any) -> ListenBrainzCandidateBatch:
        self.artist_calls += 1
        assert artist_mbid == ARTIST_MBID
        return ListenBrainzCandidateBatch(
            candidates=(candidate(CANDIDATE_ONE, "listenbrainz_artist_radio"),),
            retry_after_seconds=2.0,
        )

    def tag_radio(self, tags: tuple[str, ...], **kwargs: Any) -> ListenBrainzCandidateBatch:
        self.tag_calls += 1
        assert tags == ("trip hop", "downtempo")
        return ListenBrainzCandidateBatch(
            candidates=(candidate(CANDIDATE_TWO, "listenbrainz_tag_radio"),),
            retry_after_seconds=None,
        )

    def recording_metadata(
        self,
        recording_mbids: tuple[str, ...],
    ) -> ListenBrainzMetadataBatch:
        self.metadata_calls += 1
        return ListenBrainzMetadataBatch(
            records=tuple(
                ListenBrainzRecordingMetadata(
                    recording_mbid=mbid,
                    artist_credit=({"mbid": ARTIST_MBID, "name": "Portishead"},),
                    tags=("trip hop",),
                    release_data={"name": "Dummy"},
                    name="Roads",
                    isrcs=("GBF089400123",),
                )
                for mbid in recording_mbids
            ),
            retry_after_seconds=None,
        )


class UnavailableListenBrainz(FakeListenBrainz):
    def artist_radio(self, artist_mbid: str, **kwargs: Any) -> ListenBrainzCandidateBatch:
        del artist_mbid, kwargs
        raise ListenBrainzUnavailableError("sensitive upstream detail")

    def tag_radio(self, tags: tuple[str, ...], **kwargs: Any) -> ListenBrainzCandidateBatch:
        del tags, kwargs
        raise ListenBrainzUnavailableError("sensitive upstream detail")


ARTIST_MBID = "8ab7aa79-24a4-4a5f-b2c6-3e3c2c7af95c"
CANDIDATE_ONE = "f3bba4cd-8018-468b-902e-bc8f029593e5"
CANDIDATE_TWO = "8e74dd9d-e5a3-4acd-918a-c36a0f8cda84"


def test_discovery_job_enqueue_is_account_scoped_and_idempotent_while_active() -> None:
    now = datetime(2030, 1, 1, tzinfo=UTC)
    jobs = InMemoryJobRepository()
    seeds = InMemorySeedRepository((seed(now),))
    publisher = FakePublisher()
    service = DiscoveryJobService(
        jobs=jobs,
        seeds=seeds,
        publisher=publisher,
        now=lambda: now,
    )

    first = service.enqueue(account_id="account-1")
    replay = service.enqueue(account_id="account-1")

    assert first.id == replay.id
    assert {message["job_id"] for message in publisher.messages} == {first.id}
    assert service.get(account_id="account-2", job_id=first.id) is None


def test_discovery_worker_fetches_caches_and_persists_normalized_candidate_edges() -> None:
    now = datetime(2030, 1, 1, tzinfo=UTC)
    jobs = InMemoryJobRepository()
    seeds = InMemorySeedRepository((seed(now),))
    publisher = FakePublisher()
    job_service = DiscoveryJobService(
        jobs=jobs,
        seeds=seeds,
        publisher=publisher,
        now=lambda: now,
    )
    job = job_service.enqueue(account_id="account-1")
    entities = InMemoryEntityRepository((artist_entity(now),))
    cache = InMemoryCacheRepository()
    edges = InMemoryCandidateRepository()
    rate_limiter = FakeRateLimiter()
    listenbrainz = FakeListenBrainz()
    observed: list[dict[str, Any]] = []
    worker = DiscoveryWorker(
        jobs=jobs,
        seeds=seeds,
        entities=entities,
        cache=cache,
        candidate_edges=edges,
        rate_limiter=rate_limiter,
        listenbrainz=listenbrainz,
        now=lambda: now,
        sleep=lambda _: None,
        observer=ProductObserver(service="discovery-worker", emitter=observed.append),
    )

    completed = worker.run(account_id="account-1", job_id=job.id)

    assert completed.status == "ready"
    assert completed.error_code is None
    assert len(edges.records) == 2
    assert {edge.source_adapter for edge in edges.records.values()} == {
        "listenbrainz_artist_radio",
        "listenbrainz_tag_radio",
    }
    candidate_entity = entities.get(mbid=CANDIDATE_ONE)
    assert candidate_entity is not None
    assert candidate_entity.source == "listenbrainz"
    assert candidate_entity.name == "Roads"
    assert candidate_entity.isrcs == ("GBF089400123",)
    assert rate_limiter.reservations == ["listenbrainz", "listenbrainz", "listenbrainz"]
    assert rate_limiter.deferrals == [now + timedelta(seconds=2)]

    second_job = jobs.create_or_get(
        account_id="account-1",
        request_fingerprint="e" * 64,
        source_adapters=("listenbrainz_artist_radio", "listenbrainz_tag_radio"),
        queued_at=now,
    )
    worker.run(account_id="account-1", job_id=second_job.id)
    assert listenbrainz.artist_calls == 1
    assert listenbrainz.tag_calls == 1
    assert listenbrainz.metadata_calls == 1
    assert sum(event.get("CacheMissCount", 0) for event in observed) == 4
    assert sum(event.get("CacheHitCount", 0) for event in observed) == 4
    assert sum(event.get("SourceRequestCount", 0) for event in observed) == 3
    assert {event.get("source_status_class") for event in observed} >= {
        "success",
        "degraded",
    }


def test_discovery_worker_requeues_transient_source_failure_then_fails_boundedly() -> None:
    now = datetime(2030, 1, 1, tzinfo=UTC)
    jobs = InMemoryJobRepository()
    seeds = InMemorySeedRepository((seed(now),))
    job = DiscoveryJobService(
        jobs=jobs,
        seeds=seeds,
        publisher=FakePublisher(),
        now=lambda: now,
    ).enqueue(account_id="account-1")
    worker = DiscoveryWorker(
        jobs=jobs,
        seeds=seeds,
        entities=InMemoryEntityRepository((artist_entity(now),)),
        cache=InMemoryCacheRepository(),
        candidate_edges=InMemoryCandidateRepository(),
        rate_limiter=FakeRateLimiter(),
        listenbrainz=UnavailableListenBrainz(),
        now=lambda: now,
        sleep=lambda _: None,
    )

    with pytest.raises(DiscoveryRetryableError) as first_error:
        worker.run(account_id="account-1", job_id=job.id)
    with pytest.raises(DiscoveryRetryableError):
        worker.run(account_id="account-1", job_id=job.id)
    completed = worker.run(account_id="account-1", job_id=job.id)

    assert "sensitive" not in str(first_error.value)
    assert completed.status == "failed"
    assert completed.attempt_count == 3
    assert completed.error_code == "discovery_source_unavailable"


def test_discovery_worker_releases_claim_after_unexpected_processing_failure() -> None:
    now = datetime(2030, 1, 1, tzinfo=UTC)
    jobs = InMemoryJobRepository()
    seeds = InMemorySeedRepository((seed(now),))
    job = DiscoveryJobService(
        jobs=jobs,
        seeds=seeds,
        publisher=FakePublisher(),
        now=lambda: now,
    ).enqueue(account_id="account-1")
    worker = DiscoveryWorker(
        jobs=jobs,
        seeds=seeds,
        entities=ExplodingEntityRepository((artist_entity(now),)),
        cache=InMemoryCacheRepository(),
        candidate_edges=InMemoryCandidateRepository(),
        rate_limiter=FakeRateLimiter(),
        listenbrainz=FakeListenBrainz(),
        now=lambda: now,
        sleep=lambda _: None,
    )

    for _ in range(2):
        with pytest.raises(RuntimeError, match="unexpected entity repository failure"):
            worker.run(account_id="account-1", job_id=job.id)
        released = jobs.records[job.id]
        assert released.status == "queued"
        assert released.error_code == "discovery_worker_failure"
        assert released.started_at is None

    with pytest.raises(RuntimeError, match="unexpected entity repository failure"):
        worker.run(account_id="account-1", job_id=job.id)

    failed = jobs.records[job.id]
    assert failed.status == "failed"
    assert failed.error_code == "discovery_worker_failure"
    assert failed.attempt_count == 3


def seed(now: datetime) -> UserSeedRecord:
    return UserSeedRecord(
        id="seed-1",
        account_id="account-1",
        entity_type="artist",
        mbid=ARTIST_MBID,
        display_name="Portishead",
        position=1,
        selected_at=now,
    )


def artist_entity(now: datetime) -> MusicEntityRecord:
    return MusicEntityRecord(
        mbid=ARTIST_MBID,
        entity_type="artist",
        name="Portishead",
        artist_credit=(),
        release_data={"tags": ["trip hop", "downtempo"]},
        isrcs=(),
        source="musicbrainz",
        source_version=None,
        fetched_at=now,
        expires_at=now + timedelta(days=30),
    )


def candidate(recording_mbid: str, source_adapter: str) -> ListenBrainzCandidate:
    return ListenBrainzCandidate(
        recording_mbid=recording_mbid,
        source_adapter=source_adapter,  # type: ignore[arg-type]
        similar_artist_mbid=ARTIST_MBID,
        similar_artist_name="Portishead",
        total_listen_count=100,
        tags=(),
        source_facts={},
    )
