from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from music_recommender.models import JsonDict
from music_recommender.sources.musicbrainz import (
    MusicBrainzClient,
    MusicBrainzSearchResult,
)
from music_recommender.storage.protocols import (
    MusicEntityRecord,
    MusicEntityRepository,
    MusicEntityType,
    SourceCacheRecord,
    SourceCacheRepository,
    SourceCacheStatus,
    UserSeedInput,
    UserSeedRecord,
    UserSeedRepository,
)


class MusicBrainzSearchClient(Protocol):
    def search(
        self,
        query: str,
        *,
        entity_type: MusicEntityType,
        limit: int = 10,
    ) -> tuple[MusicBrainzSearchResult, ...]: ...


class SourceRateReservationRepository(Protocol):
    def reserve(
        self,
        *,
        source: str,
        now: datetime,
        minimum_interval_seconds: float,
    ) -> datetime: ...


@dataclass(frozen=True)
class SeedSelection:
    entity_type: MusicEntityType
    mbid: str


@dataclass(frozen=True)
class SeedSearchPage:
    results: tuple[MusicBrainzSearchResult, ...]
    cached: bool

    def to_dict(self) -> JsonDict:
        return {
            "results": [result.to_dict() for result in self.results],
            "source": "musicbrainz",
            "cached": self.cached,
        }


class SeedService:
    def __init__(
        self,
        *,
        musicbrainz: MusicBrainzSearchClient | MusicBrainzClient,
        cache: SourceCacheRepository,
        entities: MusicEntityRepository,
        seeds: UserSeedRepository,
        rate_limiter: SourceRateReservationRepository,
        now: Callable[[], datetime] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.musicbrainz = musicbrainz
        self.cache = cache
        self.entities = entities
        self.seeds = seeds
        self.rate_limiter = rate_limiter
        self.now = now or (lambda: datetime.now(UTC))
        self.sleep = sleep

    def search(
        self,
        *,
        query: str,
        entity_type: MusicEntityType,
    ) -> SeedSearchPage:
        normalized_query = _query(query)
        _entity_type(entity_type)
        now = _aware_utc(self.now())
        cache_key = _search_cache_key(normalized_query, entity_type)
        cached = self.cache.get_fresh(
            source="musicbrainz",
            cache_key=cache_key,
            now=now,
        )
        if cached is not None:
            return SeedSearchPage(results=_cached_results(cached), cached=True)

        scheduled_at = self.rate_limiter.reserve(
            source="musicbrainz",
            now=now,
            minimum_interval_seconds=1.0,
        )
        delay = max((scheduled_at - now).total_seconds(), 0.0)
        if delay:
            self.sleep(delay)
        results = self.musicbrainz.search(
            normalized_query,
            entity_type=entity_type,
            limit=10,
        )
        fetched_at = _aware_utc(self.now())
        for result in results:
            self.entities.upsert(
                MusicEntityRecord(
                    mbid=result.mbid,
                    entity_type=result.entity_type,
                    name=result.name,
                    artist_credit=result.artist_credit,
                    release_data=result.release_data,
                    isrcs=result.isrcs,
                    source="musicbrainz",
                    source_version=None,
                    fetched_at=fetched_at,
                    expires_at=fetched_at + timedelta(days=30),
                )
            )
        status: SourceCacheStatus = "fresh" if results else "negative"
        cache_ttl = timedelta(days=7) if results else timedelta(hours=1)
        self.cache.put(
            SourceCacheRecord(
                source="musicbrainz",
                cache_key=cache_key,
                status=status,
                normalized_payload={
                    "results": [result.to_dict() for result in results],
                },
                etag=None,
                fetched_at=fetched_at,
                expires_at=fetched_at + cache_ttl,
            )
        )
        return SeedSearchPage(results=results, cached=False)

    def replace(
        self,
        *,
        account_id: str,
        selections: tuple[SeedSelection, ...],
    ) -> tuple[UserSeedRecord, ...]:
        normalized_account_id = _account_id(account_id)
        if not 1 <= len(selections) <= 5:
            raise ValueError("Select between one and five seeds.")
        unique = {(selection.entity_type, _mbid(selection.mbid)) for selection in selections}
        if len(unique) != len(selections):
            raise ValueError("Selected seeds must be unique.")
        now = _aware_utc(self.now())
        inputs: list[UserSeedInput] = []
        for selection in selections:
            entity_type = _entity_type(selection.entity_type)
            mbid = _mbid(selection.mbid)
            entity = self.entities.get(mbid=mbid)
            if (
                entity is None
                or entity.entity_type != entity_type
                or entity.source != "musicbrainz"
                or entity.expires_at <= now
            ):
                raise ValueError("Search and confirm each MusicBrainz seed before selecting it.")
            inputs.append(
                UserSeedInput(
                    entity_type=entity.entity_type,
                    mbid=entity.mbid,
                    display_name=entity.name,
                )
            )
        return self.seeds.replace_active(
            account_id=normalized_account_id,
            seeds=tuple(inputs),
            selected_at=now,
        )

    def list(self, *, account_id: str) -> tuple[UserSeedRecord, ...]:
        return self.seeds.list_active(account_id=_account_id(account_id))


def seed_record_payload(seed: UserSeedRecord) -> JsonDict:
    return {
        "id": seed.id,
        "entity_type": seed.entity_type,
        "mbid": seed.mbid,
        "display_name": seed.display_name,
        "position": seed.position,
        "source": "musicbrainz",
        "selected_at": seed.selected_at.isoformat(),
    }


def _cached_results(record: SourceCacheRecord) -> tuple[MusicBrainzSearchResult, ...]:
    if record.status == "negative":
        return ()
    values = record.normalized_payload.get("results", [])
    if not isinstance(values, list):
        return ()
    results: list[MusicBrainzSearchResult] = []
    for value in values[:10]:
        if not isinstance(value, dict):
            continue
        try:
            results.append(MusicBrainzSearchResult.from_dict(value))
        except (KeyError, TypeError, ValueError):
            continue
    return tuple(results)


def _search_cache_key(query: str, entity_type: MusicEntityType) -> str:
    digest = hashlib.sha256(query.casefold().encode("utf-8")).hexdigest()
    return f"search:{entity_type}:{digest}"


def _query(value: str) -> str:
    normalized = " ".join(value.split())
    if not 2 <= len(normalized) <= 100 or any(ord(character) < 32 for character in normalized):
        raise ValueError("Search query must contain between 2 and 100 plain-text characters.")
    return normalized


def _entity_type(value: str) -> MusicEntityType:
    if value == "artist":
        return "artist"
    if value == "recording":
        return "recording"
    raise ValueError("entity_type must be artist or recording.")


def _mbid(value: str) -> str:
    try:
        return str(UUID(value))
    except ValueError:
        raise ValueError("Seed MBID must be a valid UUID.") from None


def _account_id(value: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > 255:
        raise ValueError("account_id is invalid.")
    return normalized


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Seed service timestamps must be timezone-aware.")
    return value.astimezone(UTC)
