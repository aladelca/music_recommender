from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Protocol, cast

from music_recommender.models import JsonDict
from music_recommender.observability import ProductObserver, SourceStatusClass
from music_recommender.sources.listenbrainz_api import (
    ListenBrainzCandidate,
    ListenBrainzCandidateBatch,
    ListenBrainzMetadataBatch,
    ListenBrainzRecordingMetadata,
    ListenBrainzSourceAdapter,
    ListenBrainzUnavailableError,
)
from music_recommender.storage.protocols import (
    CandidateEdgeRecord,
    CandidateEdgeRepository,
    CompletedDiscoveryJobStatus,
    DiscoveryJobRecord,
    DiscoveryJobRepository,
    MusicEntityRecord,
    MusicEntityRepository,
    SourceCacheRecord,
    SourceCacheRepository,
    SourceCacheStatus,
    SourceRateLimitRepository,
    UserSeedRecord,
)

_ALGORITHM_VERSION = "lb-core-v1"
_SOURCE_ADAPTERS = (
    "listenbrainz_artist_radio",
    "listenbrainz_tag_radio",
)
_MAX_CANDIDATES = 100
_POSITIVE_CACHE_TTL = timedelta(days=7)
_NEGATIVE_CACHE_TTL = timedelta(hours=1)
_ENTITY_CACHE_TTL = timedelta(days=30)
_MAX_SOURCE_ATTEMPTS = 3
_JOB_LEASE_DURATION = timedelta(seconds=150)


class DiscoverySeedsRequiredError(ValueError):
    pass


class DiscoveryJobNotFoundError(LookupError):
    pass


class DiscoveryRetryableError(RuntimeError):
    pass


class DiscoveryQueuePublisher(Protocol):
    def publish(
        self,
        *,
        account_id: str,
        job_id: str,
        request_fingerprint: str,
    ) -> None: ...


class ActiveSeedRepository(Protocol):
    def list_active(self, *, account_id: str) -> tuple[UserSeedRecord, ...]: ...


class ListenBrainzDiscoveryClient(Protocol):
    def artist_radio(
        self,
        artist_mbid: str,
        *,
        mode: Literal["easy", "medium", "hard"] = "medium",
        max_similar_artists: int = 10,
        max_recordings_per_artist: int = 5,
    ) -> ListenBrainzCandidateBatch: ...

    def tag_radio(
        self,
        tags: tuple[str, ...],
        *,
        count: int = 25,
    ) -> ListenBrainzCandidateBatch: ...

    def recording_metadata(
        self,
        recording_mbids: tuple[str, ...],
    ) -> ListenBrainzMetadataBatch: ...


class DiscoveryJobService:
    def __init__(
        self,
        *,
        jobs: DiscoveryJobRepository,
        seeds: ActiveSeedRepository,
        publisher: DiscoveryQueuePublisher,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.jobs = jobs
        self.seeds = seeds
        self.publisher = publisher
        self.now = now or (lambda: datetime.now(UTC))

    def enqueue(self, *, account_id: str) -> DiscoveryJobRecord:
        selected_seeds = self.seeds.list_active(account_id=account_id)
        if not selected_seeds:
            raise DiscoverySeedsRequiredError(
                "Select at least one MusicBrainz seed before starting discovery."
            )
        fingerprint = _request_fingerprint(selected_seeds)
        job = self.jobs.create_or_get(
            account_id=account_id,
            request_fingerprint=fingerprint,
            source_adapters=_SOURCE_ADAPTERS,
            queued_at=_aware_utc(self.now()),
        )
        if job.status == "queued":
            self.publisher.publish(
                account_id=account_id,
                job_id=job.id,
                request_fingerprint=fingerprint,
            )
        return job

    def get(self, *, account_id: str, job_id: str) -> DiscoveryJobRecord | None:
        return self.jobs.get(account_id=account_id, job_id=job_id)


class DiscoveryWorker:
    def __init__(
        self,
        *,
        jobs: DiscoveryJobRepository,
        seeds: ActiveSeedRepository,
        entities: MusicEntityRepository,
        cache: SourceCacheRepository,
        candidate_edges: CandidateEdgeRepository,
        rate_limiter: SourceRateLimitRepository,
        listenbrainz: ListenBrainzDiscoveryClient,
        now: Callable[[], datetime] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        observer: ProductObserver | None = None,
    ) -> None:
        self.jobs = jobs
        self.seeds = seeds
        self.entities = entities
        self.cache = cache
        self.candidate_edges = candidate_edges
        self.rate_limiter = rate_limiter
        self.listenbrainz = listenbrainz
        self.now = now or (lambda: datetime.now(UTC))
        self.sleep = sleep
        self.observer = observer

    def run(self, *, account_id: str, job_id: str) -> DiscoveryJobRecord:
        started_at = _aware_utc(self.now())
        claimed = self.jobs.claim(
            account_id=account_id,
            job_id=job_id,
            started_at=started_at,
            reclaim_started_before=started_at - _JOB_LEASE_DURATION,
        )
        if claimed is None:
            existing = self.jobs.get(account_id=account_id, job_id=job_id)
            if existing is None:
                raise DiscoveryJobNotFoundError("Discovery job was not found.")
            return existing

        try:
            return self._run_claimed(claimed)
        except DiscoveryRetryableError:
            raise
        except Exception:
            with suppress(Exception):
                if claimed.attempt_count >= _MAX_SOURCE_ATTEMPTS:
                    self._complete(
                        account_id=account_id,
                        job_id=job_id,
                        status="failed",
                        error_code="discovery_worker_failure",
                    )
                else:
                    self.jobs.release_for_retry(
                        account_id=account_id,
                        job_id=job_id,
                        error_code="discovery_worker_failure",
                    )
            raise

    def _run_claimed(self, claimed: DiscoveryJobRecord) -> DiscoveryJobRecord:
        account_id = claimed.account_id
        job_id = claimed.id
        selected_seeds = self.seeds.list_active(account_id=account_id)
        if not selected_seeds:
            return self._complete(
                account_id=account_id,
                job_id=job_id,
                status="failed",
                error_code="seeds_unavailable",
            )

        candidates: list[tuple[str, ListenBrainzCandidate]] = []
        source_degraded = False
        source_attempt_count = 0
        source_failure_count = 0
        tags: list[str] = []
        for seed in selected_seeds:
            seed_entity = self.entities.get(mbid=seed.mbid)
            if seed_entity is None:
                source_degraded = True
                continue
            tags.extend(_entity_tags(seed_entity))
            for artist_mbid in _seed_artist_mbids(seed, seed_entity):
                source_attempt_count += 1
                try:
                    batch = self._artist_candidates(artist_mbid)
                except ListenBrainzUnavailableError:
                    source_degraded = True
                    source_failure_count += 1
                    continue
                candidates.extend((seed.mbid, candidate) for candidate in batch)

        selected_tags = _unique_tags(tags, limit=3)
        if selected_tags:
            source_attempt_count += 1
            try:
                tag_candidates = self._tag_candidates(selected_tags)
            except ListenBrainzUnavailableError:
                source_degraded = True
                source_failure_count += 1
            else:
                for seed in selected_seeds:
                    candidates.extend((seed.mbid, candidate) for candidate in tag_candidates)

        bounded_candidates = _unique_candidates(candidates, limit=_MAX_CANDIDATES)
        if not bounded_candidates:
            if source_attempt_count and source_failure_count == source_attempt_count:
                return self._retry_or_fail(claimed)
            return self._complete(
                account_id=account_id,
                job_id=job_id,
                status="failed",
                error_code=("discovery_source_unavailable" if source_degraded else "no_candidates"),
            )

        candidate_mbids = tuple(
            dict.fromkeys(candidate.recording_mbid for _, candidate in bounded_candidates)
        )
        try:
            metadata = self._recording_metadata(candidate_mbids)
        except ListenBrainzUnavailableError:
            metadata = {}
            source_degraded = True

        fetched_at = _aware_utc(self.now())
        for seed_mbid, candidate in bounded_candidates:
            record_metadata = metadata.get(candidate.recording_mbid)
            self.entities.upsert(
                _candidate_entity(
                    candidate=candidate,
                    metadata=record_metadata,
                    fetched_at=fetched_at,
                )
            )
            self.candidate_edges.upsert(
                CandidateEdgeRecord(
                    seed_mbid=seed_mbid,
                    candidate_recording_mbid=candidate.recording_mbid,
                    source_adapter=candidate.source_adapter,
                    algorithm_version=_ALGORITHM_VERSION,
                    strength=_candidate_strength(candidate),
                    listener_count=candidate.total_listen_count,
                    source_facts=_candidate_source_facts(candidate),
                    fetched_at=fetched_at,
                    expires_at=fetched_at + _POSITIVE_CACHE_TTL,
                )
            )

        return self._complete(
            account_id=account_id,
            job_id=job_id,
            status="degraded" if source_degraded else "ready",
            error_code="partial_source_coverage" if source_degraded else None,
        )

    def _retry_or_fail(self, job: DiscoveryJobRecord) -> DiscoveryJobRecord:
        if job.attempt_count < _MAX_SOURCE_ATTEMPTS:
            self.jobs.release_for_retry(
                account_id=job.account_id,
                job_id=job.id,
                error_code="discovery_source_unavailable",
            )
            raise DiscoveryRetryableError("Automated discovery source is temporarily unavailable.")
        return self._complete(
            account_id=job.account_id,
            job_id=job.id,
            status="failed",
            error_code="discovery_source_unavailable",
        )

    def _artist_candidates(
        self,
        artist_mbid: str,
    ) -> tuple[ListenBrainzCandidate, ...]:
        cache_key = f"radio:artist:{artist_mbid}:{_ALGORITHM_VERSION}"
        cached = self._cached_candidates(cache_key)
        if cached is not None:
            return cached
        self._reserve_source_call()
        try:
            batch = self.listenbrainz.artist_radio(artist_mbid)
        except ListenBrainzUnavailableError:
            self._observe_source("transient_failure")
            raise
        self._observe_source("degraded" if batch.retry_after_seconds else "success")
        self._observe_retry_after(batch.retry_after_seconds)
        self._cache_candidates(cache_key, batch.candidates)
        return batch.candidates

    def _tag_candidates(self, tags: tuple[str, ...]) -> tuple[ListenBrainzCandidate, ...]:
        digest = hashlib.sha256("\0".join(tags).encode("utf-8")).hexdigest()
        cache_key = f"radio:tags:{digest}:{_ALGORITHM_VERSION}"
        cached = self._cached_candidates(cache_key)
        if cached is not None:
            return cached
        self._reserve_source_call()
        try:
            batch = self.listenbrainz.tag_radio(tags)
        except ListenBrainzUnavailableError:
            self._observe_source("transient_failure")
            raise
        self._observe_source("degraded" if batch.retry_after_seconds else "success")
        self._observe_retry_after(batch.retry_after_seconds)
        self._cache_candidates(cache_key, batch.candidates)
        return batch.candidates

    def _recording_metadata(
        self,
        recording_mbids: tuple[str, ...],
    ) -> dict[str, ListenBrainzRecordingMetadata]:
        records: dict[str, ListenBrainzRecordingMetadata] = {}
        missing: list[str] = []
        for recording_mbid in recording_mbids:
            cache_key = _metadata_cache_key(recording_mbid)
            cached = self.cache.get_fresh(
                source="listenbrainz",
                cache_key=cache_key,
                now=_aware_utc(self.now()),
            )
            if cached is None:
                self._observe_cache(hit=False, status="missing")
                missing.append(recording_mbid)
                continue
            self._observe_cache(hit=True, status=cached.status)
            if cached.status == "fresh":
                parsed = _metadata_from_payload(cached.normalized_payload)
                if parsed is not None:
                    records[recording_mbid] = parsed

        if not missing:
            return records
        self._reserve_source_call()
        try:
            batch = self.listenbrainz.recording_metadata(tuple(missing))
        except ListenBrainzUnavailableError:
            self._observe_source("transient_failure")
            raise
        self._observe_source("degraded" if batch.retry_after_seconds else "success")
        self._observe_retry_after(batch.retry_after_seconds)
        fetched_at = _aware_utc(self.now())
        fetched_records = {record.recording_mbid: record for record in batch.records}
        for recording_mbid in missing:
            record = fetched_records.get(recording_mbid)
            status: SourceCacheStatus = "fresh" if record is not None else "negative"
            payload = _metadata_payload(record) if record is not None else {}
            self.cache.put(
                SourceCacheRecord(
                    source="listenbrainz",
                    cache_key=_metadata_cache_key(recording_mbid),
                    status=status,
                    normalized_payload=payload,
                    etag=None,
                    fetched_at=fetched_at,
                    expires_at=fetched_at
                    + (_POSITIVE_CACHE_TTL if record is not None else _NEGATIVE_CACHE_TTL),
                )
            )
            if record is not None:
                records[recording_mbid] = record
        return records

    def _cached_candidates(
        self,
        cache_key: str,
    ) -> tuple[ListenBrainzCandidate, ...] | None:
        cached = self.cache.get_fresh(
            source="listenbrainz",
            cache_key=cache_key,
            now=_aware_utc(self.now()),
        )
        if cached is None:
            self._observe_cache(hit=False, status="missing")
            return None
        self._observe_cache(hit=True, status=cached.status)
        values = cached.normalized_payload.get("candidates", [])
        if not isinstance(values, list):
            return ()
        candidates: list[ListenBrainzCandidate] = []
        for value in values[:_MAX_CANDIDATES]:
            if not isinstance(value, dict):
                continue
            candidate = _candidate_from_payload(value)
            if candidate is not None:
                candidates.append(candidate)
        return tuple(candidates)

    def _cache_candidates(
        self,
        cache_key: str,
        candidates: tuple[ListenBrainzCandidate, ...],
    ) -> None:
        fetched_at = _aware_utc(self.now())
        bounded = candidates[:_MAX_CANDIDATES]
        self.cache.put(
            SourceCacheRecord(
                source="listenbrainz",
                cache_key=cache_key,
                status="fresh" if bounded else "negative",
                normalized_payload={"candidates": [candidate.to_dict() for candidate in bounded]},
                etag=None,
                fetched_at=fetched_at,
                expires_at=fetched_at + (_POSITIVE_CACHE_TTL if bounded else _NEGATIVE_CACHE_TTL),
            )
        )

    def _reserve_source_call(self) -> None:
        now = _aware_utc(self.now())
        scheduled_at = self.rate_limiter.reserve(
            source="listenbrainz",
            now=now,
            minimum_interval_seconds=1.0,
        )
        delay = max((scheduled_at - now).total_seconds(), 0.0)
        if delay:
            self.sleep(delay)

    def _observe_retry_after(self, retry_after_seconds: float | None) -> None:
        if retry_after_seconds is None or retry_after_seconds <= 0:
            return
        self.rate_limiter.defer(
            source="listenbrainz",
            not_before=_aware_utc(self.now()) + timedelta(seconds=retry_after_seconds),
        )

    def _observe_cache(
        self,
        *,
        hit: bool,
        status: Literal["fresh", "negative", "error", "missing"],
    ) -> None:
        if self.observer is not None:
            self.observer.cache_lookup(
                source="listenbrainz",
                hit=hit,
                cache_status=status,
            )

    def _observe_source(self, status: SourceStatusClass) -> None:
        if self.observer is not None:
            self.observer.source_request(source="listenbrainz", status_class=status)

    def _complete(
        self,
        *,
        account_id: str,
        job_id: str,
        status: CompletedDiscoveryJobStatus,
        error_code: str | None,
    ) -> DiscoveryJobRecord:
        return self.jobs.complete(
            account_id=account_id,
            job_id=job_id,
            status=status,
            error_code=error_code,
            completed_at=_aware_utc(self.now()),
        )


def discovery_job_payload(job: DiscoveryJobRecord) -> JsonDict:
    return {
        "id": job.id,
        "status": job.status,
        "source_adapters": list(job.source_adapters),
        "attempt_count": job.attempt_count,
        "error_code": job.error_code,
        "queued_at": job.queued_at.isoformat(),
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
    }


def _request_fingerprint(seeds: tuple[UserSeedRecord, ...]) -> str:
    payload = {
        "algorithm_version": _ALGORITHM_VERSION,
        "source_adapters": list(_SOURCE_ADAPTERS),
        "seeds": [
            {"entity_type": seed.entity_type, "mbid": seed.mbid}
            for seed in sorted(seeds, key=lambda seed: (seed.position, seed.mbid))
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _seed_artist_mbids(
    seed: UserSeedRecord,
    entity: MusicEntityRecord,
) -> tuple[str, ...]:
    if seed.entity_type == "artist":
        return (seed.mbid,)
    mbids: list[str] = []
    for artist in entity.artist_credit:
        mbid = artist.get("mbid")
        if isinstance(mbid, str) and mbid not in mbids:
            mbids.append(mbid)
    return tuple(mbids[:5])


def _entity_tags(entity: MusicEntityRecord) -> tuple[str, ...]:
    values = entity.release_data.get("tags", [])
    if not isinstance(values, list):
        return ()
    return _unique_tags((value for value in values if isinstance(value, str)), limit=3)


def _unique_tags(values: Any, *, limit: int) -> tuple[str, ...]:
    tags: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = " ".join(str(value).split())
        folded = normalized.casefold()
        if not normalized or folded in seen:
            continue
        seen.add(folded)
        tags.append(normalized[:64])
        if len(tags) == limit:
            break
    return tuple(tags)


def _unique_candidates(
    values: list[tuple[str, ListenBrainzCandidate]],
    *,
    limit: int,
) -> tuple[tuple[str, ListenBrainzCandidate], ...]:
    unique: list[tuple[str, ListenBrainzCandidate]] = []
    seen: set[tuple[str, str, str]] = set()
    for seed_mbid, candidate in values:
        key = (seed_mbid, candidate.recording_mbid, candidate.source_adapter)
        if key in seen:
            continue
        seen.add(key)
        unique.append((seed_mbid, candidate))
        if len(unique) == limit:
            break
    return tuple(unique)


def _candidate_entity(
    *,
    candidate: ListenBrainzCandidate,
    metadata: ListenBrainzRecordingMetadata | None,
    fetched_at: datetime,
) -> MusicEntityRecord:
    release_data = dict(metadata.release_data) if metadata is not None else {}
    tags = metadata.tags if metadata is not None else candidate.tags
    release_data["tags"] = list(tags)
    release_data["metadata_pending"] = True
    return MusicEntityRecord(
        mbid=candidate.recording_mbid,
        entity_type="recording",
        name=(
            metadata.name if metadata is not None and metadata.name else candidate.recording_mbid
        ),
        artist_credit=metadata.artist_credit if metadata is not None else (),
        release_data=release_data,
        isrcs=metadata.isrcs if metadata is not None else (),
        source="listenbrainz",
        source_version=_ALGORITHM_VERSION,
        fetched_at=fetched_at,
        expires_at=fetched_at + _ENTITY_CACHE_TTL,
    )


def _candidate_source_facts(candidate: ListenBrainzCandidate) -> JsonDict:
    facts = dict(candidate.source_facts)
    facts.update(
        {
            "similar_artist_mbid": candidate.similar_artist_mbid,
            "similar_artist_name": candidate.similar_artist_name,
            "tags": list(candidate.tags),
        }
    )
    return facts


def _candidate_strength(candidate: ListenBrainzCandidate) -> float | None:
    percent = candidate.source_facts.get("percent")
    if isinstance(percent, (int, float)) and not isinstance(percent, bool):
        return max(0.0, min(float(percent) / 100.0, 1.0))
    return None


def _candidate_from_payload(value: dict[str, Any]) -> ListenBrainzCandidate | None:
    recording_mbid = value.get("recording_mbid")
    source_adapter = value.get("source_adapter")
    if not isinstance(recording_mbid, str) or source_adapter not in _SOURCE_ADAPTERS:
        return None
    tags = value.get("tags", [])
    facts = value.get("source_facts", {})
    if not isinstance(tags, list) or not isinstance(facts, dict):
        return None
    listener_count = value.get("total_listen_count")
    return ListenBrainzCandidate(
        recording_mbid=recording_mbid,
        source_adapter=cast(ListenBrainzSourceAdapter, source_adapter),
        similar_artist_mbid=_optional_string(value.get("similar_artist_mbid")),
        similar_artist_name=_optional_string(value.get("similar_artist_name")),
        total_listen_count=(listener_count if isinstance(listener_count, int) else None),
        tags=tuple(tag for tag in tags if isinstance(tag, str))[:3],
        source_facts={str(key): item for key, item in facts.items()},
    )


def _metadata_cache_key(recording_mbid: str) -> str:
    return f"metadata:recording:{recording_mbid}:v1"


def _metadata_payload(metadata: ListenBrainzRecordingMetadata) -> JsonDict:
    return {
        "recording_mbid": metadata.recording_mbid,
        "artist_credit": list(metadata.artist_credit),
        "tags": list(metadata.tags),
        "release_data": dict(metadata.release_data),
        "name": metadata.name,
        "isrcs": list(metadata.isrcs),
    }


def _metadata_from_payload(value: dict[str, Any]) -> ListenBrainzRecordingMetadata | None:
    recording_mbid = value.get("recording_mbid")
    artist_credit = value.get("artist_credit", [])
    tags = value.get("tags", [])
    release_data = value.get("release_data", {})
    name = value.get("name")
    isrcs = value.get("isrcs", [])
    if (
        not isinstance(recording_mbid, str)
        or not isinstance(artist_credit, list)
        or not isinstance(tags, list)
        or not isinstance(release_data, dict)
        or (name is not None and not isinstance(name, str))
        or not isinstance(isrcs, list)
    ):
        return None
    return ListenBrainzRecordingMetadata(
        recording_mbid=recording_mbid,
        artist_credit=tuple(item for item in artist_credit if isinstance(item, dict)),
        tags=tuple(item for item in tags if isinstance(item, str)),
        release_data={str(key): item for key, item in release_data.items()},
        name=name,
        isrcs=tuple(item for item in isrcs if isinstance(item, str)),
    )


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Discovery timestamps must be timezone-aware.")
    return value.astimezone(UTC)
