from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from music_recommender.product.seed_service import SeedSelection, SeedService
from music_recommender.sources.musicbrainz import MusicBrainzSearchResult
from music_recommender.storage.protocols import (
    MusicEntityRecord,
    SourceCacheRecord,
    UserSeedInput,
    UserSeedRecord,
)


class InMemoryCacheRepository:
    def __init__(self) -> None:
        self.records: dict[tuple[str, str], SourceCacheRecord] = {}

    def put(self, record: SourceCacheRecord) -> SourceCacheRecord:
        self.records[(record.source, record.cache_key)] = record
        return record

    def get_fresh(
        self,
        *,
        source: str,
        cache_key: str,
        now: datetime,
    ) -> SourceCacheRecord | None:
        record = self.records.get((source, cache_key))
        return record if record and record.expires_at > now else None


class InMemoryEntityRepository:
    def __init__(self) -> None:
        self.records: dict[str, MusicEntityRecord] = {}

    def upsert(self, entity: MusicEntityRecord) -> MusicEntityRecord:
        self.records[entity.mbid] = entity
        return entity

    def get(self, *, mbid: str) -> MusicEntityRecord | None:
        return self.records.get(mbid)


class InMemorySeedRepository:
    def __init__(self) -> None:
        self.records: dict[str, tuple[UserSeedRecord, ...]] = {}

    def replace_active(
        self,
        *,
        account_id: str,
        seeds: tuple[UserSeedInput, ...],
        selected_at: datetime,
    ) -> tuple[UserSeedRecord, ...]:
        records = tuple(
            UserSeedRecord(
                id=f"seed-{position}",
                account_id=account_id,
                entity_type=seed.entity_type,
                mbid=seed.mbid,
                display_name=seed.display_name,
                position=position,
                selected_at=selected_at,
            )
            for position, seed in enumerate(seeds, start=1)
        )
        self.records[account_id] = records
        return records

    def list_active(self, *, account_id: str) -> tuple[UserSeedRecord, ...]:
        return self.records.get(account_id, ())


class FakeRateLimiter:
    def __init__(self, delay_seconds: float = 0.0) -> None:
        self.delay_seconds = delay_seconds
        self.calls: list[tuple[str, datetime, float]] = []

    def reserve(
        self,
        *,
        source: str,
        now: datetime,
        minimum_interval_seconds: float,
    ) -> datetime:
        self.calls.append((source, now, minimum_interval_seconds))
        return now + timedelta(seconds=self.delay_seconds)


class FakeMusicBrainzClient:
    def __init__(self, results: tuple[MusicBrainzSearchResult, ...]) -> None:
        self.results = results
        self.calls: list[tuple[str, str, int]] = []

    def search(
        self,
        query: str,
        *,
        entity_type: str,
        limit: int = 10,
    ) -> tuple[MusicBrainzSearchResult, ...]:
        self.calls.append((query, entity_type, limit))
        return self.results


def test_seed_search_uses_distributed_limit_and_supabase_cache() -> None:
    now = datetime(2030, 1, 1, tzinfo=UTC)
    client = FakeMusicBrainzClient((artist_result(),))
    cache = InMemoryCacheRepository()
    entities = InMemoryEntityRepository()
    limiter = FakeRateLimiter(delay_seconds=0.25)
    sleeps: list[float] = []
    service = SeedService(
        musicbrainz=client,
        cache=cache,
        entities=entities,
        seeds=InMemorySeedRepository(),
        rate_limiter=limiter,
        now=lambda: now,
        sleep=sleeps.append,
    )

    first = service.search(query=" Portishead ", entity_type="artist")
    second = service.search(query="portishead", entity_type="artist")

    assert first.cached is False
    assert second.cached is True
    assert first.results == (artist_result(),)
    assert client.calls == [("Portishead", "artist", 10)]
    assert limiter.calls == [("musicbrainz", now, 1.0)]
    assert sleeps == [0.25]
    assert entities.get(mbid=artist_result().mbid) is not None
    cached = next(iter(cache.records.values()))
    assert cached.status == "fresh"
    assert cached.expires_at == now + timedelta(days=7)


def test_seed_search_caches_negative_results_for_one_hour() -> None:
    now = datetime(2030, 1, 1, tzinfo=UTC)
    client = FakeMusicBrainzClient(())
    cache = InMemoryCacheRepository()
    service = SeedService(
        musicbrainz=client,
        cache=cache,
        entities=InMemoryEntityRepository(),
        seeds=InMemorySeedRepository(),
        rate_limiter=FakeRateLimiter(),
        now=lambda: now,
        sleep=lambda _: None,
    )

    assert service.search(query="No Such Artist", entity_type="artist").results == ()
    cached = next(iter(cache.records.values()))
    assert cached.status == "negative"
    assert cached.expires_at == now + timedelta(hours=1)


def test_explicit_seed_selection_uses_canonical_entity_and_is_account_scoped() -> None:
    now = datetime(2030, 1, 1, tzinfo=UTC)
    entities = InMemoryEntityRepository()
    entity = MusicEntityRecord(
        mbid=artist_result().mbid,
        entity_type="artist",
        name="Canonical Portishead",
        artist_credit=(),
        release_data={},
        isrcs=(),
        source="musicbrainz",
        source_version=None,
        fetched_at=now,
        expires_at=now + timedelta(days=30),
    )
    entities.upsert(entity)
    seeds = InMemorySeedRepository()
    service = SeedService(
        musicbrainz=FakeMusicBrainzClient(()),
        cache=InMemoryCacheRepository(),
        entities=entities,
        seeds=seeds,
        rate_limiter=FakeRateLimiter(),
        now=lambda: now,
        sleep=lambda _: None,
    )

    selected = service.replace(
        account_id="account-1",
        selections=(SeedSelection(entity_type="artist", mbid=entity.mbid),),
    )

    assert selected[0].display_name == "Canonical Portishead"
    assert service.list(account_id="account-1") == selected
    assert service.list(account_id="account-2") == ()


@pytest.mark.parametrize(
    "selection",
    [
        SeedSelection(
            entity_type="recording",
            mbid="8ab7aa79-24a4-4a5f-b2c6-3e3c2c7af95c",
        ),
        SeedSelection(
            entity_type="artist",
            mbid="00000000-0000-0000-0000-000000000000",
        ),
    ],
)
def test_explicit_seed_selection_rejects_unknown_or_mismatched_entity(
    selection: SeedSelection,
) -> None:
    now = datetime(2030, 1, 1, tzinfo=UTC)
    entities = InMemoryEntityRepository()
    entities.upsert(
        MusicEntityRecord(
            mbid="8ab7aa79-24a4-4a5f-b2c6-3e3c2c7af95c",
            entity_type="artist",
            name="Portishead",
            artist_credit=(),
            release_data={},
            isrcs=(),
            source="musicbrainz",
            source_version=None,
            fetched_at=now,
            expires_at=now + timedelta(days=30),
        )
    )
    service = SeedService(
        musicbrainz=FakeMusicBrainzClient(()),
        cache=InMemoryCacheRepository(),
        entities=entities,
        seeds=InMemorySeedRepository(),
        rate_limiter=FakeRateLimiter(),
        now=lambda: now,
        sleep=lambda _: None,
    )

    with pytest.raises(ValueError, match="Search and confirm"):
        service.replace(account_id="account-1", selections=(selection,))


def artist_result() -> MusicBrainzSearchResult:
    return MusicBrainzSearchResult(
        mbid="8ab7aa79-24a4-4a5f-b2c6-3e3c2c7af95c",
        entity_type="artist",
        name="Portishead",
        artist_credit=(),
        release_data={"country": "GB"},
        isrcs=(),
    )
