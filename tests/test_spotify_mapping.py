from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from music_recommender.product.spotify_mapping import (
    SpotifyMappingService,
    evaluate_source_coverage,
)
from music_recommender.storage.protocols import (
    ExternalIdMappingRecord,
    MusicEntityRecord,
)

RECORDING_ONE = "10000000-0000-0000-0000-000000000001"
RECORDING_TWO = "10000000-0000-0000-0000-000000000002"


class InMemoryEntities:
    def __init__(self, entities: tuple[MusicEntityRecord, ...]) -> None:
        self.records = {entity.mbid: entity for entity in entities}

    def get(self, *, mbid: str) -> MusicEntityRecord | None:
        return self.records.get(mbid)


class InMemoryMappings:
    def __init__(self) -> None:
        self.records: dict[str, ExternalIdMappingRecord] = {}

    def get_fresh(
        self,
        *,
        recording_mbid: str,
        provider: str,
        now: datetime,
    ) -> ExternalIdMappingRecord | None:
        assert provider == "spotify"
        record = self.records.get(recording_mbid)
        return record if record and record.expires_at > now else None

    def upsert(self, record: ExternalIdMappingRecord) -> ExternalIdMappingRecord:
        self.records[record.recording_mbid] = record
        return record


class FakeSpotifySearch:
    def __init__(self, responses: dict[str, tuple[dict[str, Any], ...]]) -> None:
        self.responses = responses
        self.queries: list[str] = []

    def search_tracks(
        self,
        query: str,
        *,
        limit: int = 5,
        market: str | None = None,
    ) -> tuple[dict[str, Any], ...]:
        assert limit == 5
        assert market == "CA"
        self.queries.append(query)
        return self.responses.get(query, ())


def test_spotify_mapping_runs_after_ranking_and_prefers_exact_isrc() -> None:
    now = datetime(2030, 1, 1, tzinfo=UTC)
    entities = InMemoryEntities((recording(RECORDING_ONE, "Roads", ("GBF089400123",)),))
    mappings = InMemoryMappings()
    spotify = FakeSpotifySearch(
        {
            "isrc:GBF089400123": (
                spotify_track(
                    track_id="popular-wrong-isrc",
                    name="Roads",
                    artist="Portishead",
                    isrc="USZZZ9999999",
                    popularity=100,
                ),
                spotify_track(
                    track_id="spotify-1",
                    name="Roads",
                    artist="Portishead",
                    isrc="GBF089400123",
                    popularity=0,
                ),
            )
        }
    )
    service = SpotifyMappingService(
        entities=entities,
        mappings=mappings,
        spotify=spotify,
        market="CA",
        now=lambda: now,
    )

    result = service.map_ranked(recording_mbids=(RECORDING_ONE,))

    assert [mapping.provider_id for mapping in result.mappings] == ["spotify-1"]
    assert result.mappings[0].mapping_source == "isrc_exact"
    assert result.mappings[0].confidence == 1.0
    assert result.unmapped_recording_mbids == ()
    assert spotify.queries == ["isrc:GBF089400123"]
    assert result.mappings[0].expires_at == now + timedelta(hours=24)
    assert "popularity" not in result.mappings[0].mapping_source

    cached = service.map_ranked(recording_mbids=(RECORDING_ONE,))
    assert cached.mappings == result.mappings
    assert spotify.queries == ["isrc:GBF089400123"]


def test_spotify_mapping_falls_back_to_exact_name_and_artist_without_fuzzy_match() -> None:
    now = datetime(2030, 1, 1, tzinfo=UTC)
    entities = InMemoryEntities((recording(RECORDING_TWO, "Glory Box", ()),))
    mappings = InMemoryMappings()
    spotify = FakeSpotifySearch(
        {
            'track:"Glory Box" artist:"Portishead"': (
                spotify_track(
                    track_id="wrong",
                    name="Glory Box (Remix)",
                    artist="Portishead",
                    isrc=None,
                ),
                spotify_track(
                    track_id="spotify-2",
                    name="Glory Box",
                    artist="Portishead",
                    isrc=None,
                ),
            )
        }
    )
    service = SpotifyMappingService(
        entities=entities,
        mappings=mappings,
        spotify=spotify,
        market="CA",
        now=lambda: now,
    )

    result = service.map_ranked(recording_mbids=(RECORDING_TWO,))

    assert result.mappings[0].provider_id == "spotify-2"
    assert result.mappings[0].mapping_source == "name_artist_exact"
    assert result.mappings[0].confidence == 0.9


def test_source_coverage_requires_ten_mapped_and_ninety_percent_evidence() -> None:
    ranked = tuple(f"10000000-0000-0000-0000-{index:012d}" for index in range(1, 13))

    ready = evaluate_source_coverage(
        ranked_recording_mbids=ranked + (ranked[0],),
        mapped_recording_mbids=ranked[:10],
        evidenced_recording_mbids=ranked[:9],
    )
    degraded = evaluate_source_coverage(
        ranked_recording_mbids=ranked,
        mapped_recording_mbids=ranked[:10],
        evidenced_recording_mbids=ranked[:8],
    )
    insufficient = evaluate_source_coverage(
        ranked_recording_mbids=ranked,
        mapped_recording_mbids=ranked[:9],
        evidenced_recording_mbids=ranked[:9],
    )

    assert ready.status == "ready"
    assert ready.returnable_recording_mbids == ranked[:10]
    assert ready.duplicate_count == 1
    assert ready.evidence_coverage == 0.9
    assert degraded.status == "degraded"
    assert degraded.limitations == ("evidence_coverage_below_90_percent",)
    assert insufficient.status == "insufficient"
    assert insufficient.limitations == ("fewer_than_10_spotify_mappings",)


def recording(
    mbid: str,
    name: str,
    isrcs: tuple[str, ...],
) -> MusicEntityRecord:
    now = datetime(2030, 1, 1, tzinfo=UTC)
    return MusicEntityRecord(
        mbid=mbid,
        entity_type="recording",
        name=name,
        artist_credit=(
            {
                "mbid": "20000000-0000-0000-0000-000000000001",
                "name": "Portishead",
            },
        ),
        release_data={},
        isrcs=isrcs,
        source="listenbrainz",
        source_version="lb-core-v1",
        fetched_at=now,
        expires_at=now + timedelta(days=30),
    )


def spotify_track(
    *,
    track_id: str,
    name: str,
    artist: str,
    isrc: str | None,
    popularity: int | None = None,
) -> dict[str, Any]:
    return {
        "id": track_id,
        "name": name,
        "artists": [{"name": artist}],
        "external_ids": {"isrc": isrc} if isrc else {},
        "external_urls": {"spotify": f"https://open.spotify.com/track/{track_id}"},
        "popularity": popularity,
    }
