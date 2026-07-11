from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest

from music_recommender.agents.intent import AdventureMode, DiscoveryIntent
from music_recommender.recommender.models import DiscoveryRankingPreferences
from music_recommender.recommender.scoring import rank_discovery_candidates
from music_recommender.storage.protocols import (
    CandidateEdgeRecord,
    CandidateSourceAdapter,
    MusicEntityRecord,
)

SEED = "10000000-0000-0000-0000-000000000001"
ARTIST_ONE = "20000000-0000-0000-0000-000000000001"
ARTIST_TWO = "20000000-0000-0000-0000-000000000002"
RECORDING_ONE = "30000000-0000-0000-0000-000000000001"
RECORDING_TWO = "30000000-0000-0000-0000-000000000002"
RECORDING_THREE = "30000000-0000-0000-0000-000000000003"


def test_discovery_ranker_uses_versioned_independent_component_weights() -> None:
    entity = recording(RECORDING_ONE, ARTIST_ONE, tags=("ambient", "downtempo"))
    candidate_edge = edge(RECORDING_ONE, strength=0.8, listener_count=1_000)
    intent = discovery_intent(tags=("ambient", "downtempo"))

    ranked = rank_discovery_candidates(
        (candidate_edge,),
        entities={RECORDING_ONE: entity},
        intent=intent,
        selected_seed_mbids=(SEED,),
    )

    expected_discovery = 1 - (math.log1p(1_000) / math.log1p(1_000_000))
    expected_total = 0.35 + (0.30 * 0.8) + (0.20 * expected_discovery) + 0.15
    assert ranked[0].ranking_version == "explicit-discovery-v1"
    assert ranked[0].score.prompt_tag_fit == 1.0
    assert ranked[0].score.seed_bridge_strength == 0.8
    assert ranked[0].score.discovery_value == pytest.approx(expected_discovery)
    assert ranked[0].score.evidence_quality == 1.0
    assert ranked[0].score.total == pytest.approx(expected_total)


def test_adventure_mode_shifts_bridge_and_discovery_without_spotify_popularity() -> None:
    entities = {
        RECORDING_ONE: recording(RECORDING_ONE, ARTIST_ONE, tags=("ambient",)),
        RECORDING_TWO: recording(RECORDING_TWO, ARTIST_TWO, tags=("ambient",)),
    }
    edges = (
        edge(RECORDING_ONE, strength=1.0, listener_count=1_000_000),
        edge(RECORDING_TWO, strength=0.4, listener_count=0),
    )

    familiar = rank_discovery_candidates(
        edges,
        entities=entities,
        intent=discovery_intent(tags=("ambient",), adventure="familiar"),
        selected_seed_mbids=(SEED,),
        limit=1,
    )
    adventurous = rank_discovery_candidates(
        edges,
        entities=entities,
        intent=discovery_intent(tags=("ambient",), adventure="adventurous"),
        selected_seed_mbids=(SEED,),
        limit=1,
    )

    assert familiar[0].entity.mbid == RECORDING_ONE
    assert adventurous[0].entity.mbid == RECORDING_TWO


def test_discovery_ranker_filters_seeds_blocks_explicit_and_enforces_artist_diversity() -> None:
    entities = {
        SEED: recording(SEED, ARTIST_TWO),
        RECORDING_ONE: recording(RECORDING_ONE, ARTIST_ONE),
        RECORDING_TWO: recording(RECORDING_TWO, ARTIST_ONE),
        RECORDING_THREE: recording(RECORDING_THREE, ARTIST_TWO, explicit=True),
    }
    edges = (
        edge(SEED, strength=1.0),
        edge(RECORDING_ONE, strength=0.9),
        edge(RECORDING_ONE, strength=0.8, source="listenbrainz_tag_radio"),
        edge(RECORDING_TWO, strength=0.7),
        edge(RECORDING_THREE, strength=0.95),
    )

    ranked = rank_discovery_candidates(
        edges,
        entities=entities,
        intent=discovery_intent(allow_explicit=False),
        selected_seed_mbids=(SEED,),
    )
    recording_blocked = rank_discovery_candidates(
        edges,
        entities=entities,
        intent=discovery_intent(allow_explicit=False),
        selected_seed_mbids=(SEED,),
        preferences=DiscoveryRankingPreferences(
            blocked_recording_mbids=(RECORDING_ONE,),
        ),
    )

    assert [candidate.entity.mbid for candidate in ranked] == [RECORDING_ONE]
    assert len(ranked[0].edges) == 2
    assert [candidate.entity.mbid for candidate in recording_blocked] == [RECORDING_TWO]


def test_discovery_ranker_applies_first_party_artist_blocks_and_deterministic_ties() -> None:
    entities = {
        RECORDING_ONE: recording(RECORDING_ONE, ARTIST_ONE),
        RECORDING_TWO: recording(RECORDING_TWO, ARTIST_TWO),
    }
    edges = (
        edge(RECORDING_TWO, strength=0.5),
        edge(RECORDING_ONE, strength=0.5),
    )
    intent = discovery_intent()

    tied = rank_discovery_candidates(
        edges,
        entities=entities,
        intent=intent,
        selected_seed_mbids=(SEED,),
    )
    blocked = rank_discovery_candidates(
        edges,
        entities=entities,
        intent=intent,
        selected_seed_mbids=(SEED,),
        preferences=DiscoveryRankingPreferences(blocked_artist_mbids=(ARTIST_ONE,)),
    )

    assert [candidate.entity.mbid for candidate in tied] == [RECORDING_ONE, RECORDING_TWO]
    assert [candidate.entity.mbid for candidate in blocked] == [RECORDING_TWO]


def discovery_intent(
    *,
    tags: tuple[str, ...] = (),
    adventure: AdventureMode = "balanced",
    allow_explicit: bool = True,
) -> DiscoveryIntent:
    return DiscoveryIntent(
        label="test",
        tags=tags,
        adventure=adventure,
        allow_explicit=allow_explicit,
        parser_version="test-v1",
    )


def recording(
    mbid: str,
    artist_mbid: str,
    *,
    tags: tuple[str, ...] = (),
    explicit: bool | None = None,
) -> MusicEntityRecord:
    now = datetime(2030, 1, 1, tzinfo=UTC)
    release_data: dict[str, object] = {"tags": list(tags)}
    if explicit is not None:
        release_data["explicit"] = explicit
    return MusicEntityRecord(
        mbid=mbid,
        entity_type="recording",
        name=f"Recording {mbid[-1]}",
        artist_credit=({"mbid": artist_mbid, "name": f"Artist {artist_mbid[-1]}"},),
        release_data=release_data,
        isrcs=(),
        source="listenbrainz",
        source_version="lb-core-v1",
        fetched_at=now,
        expires_at=now + timedelta(days=30),
    )


def edge(
    recording_mbid: str,
    *,
    strength: float,
    listener_count: int | None = None,
    source: CandidateSourceAdapter = "listenbrainz_artist_radio",
) -> CandidateEdgeRecord:
    now = datetime(2030, 1, 1, tzinfo=UTC)
    return CandidateEdgeRecord(
        seed_mbid=SEED,
        candidate_recording_mbid=recording_mbid,
        source_adapter=source,
        algorithm_version="lb-core-v1",
        strength=strength,
        listener_count=listener_count,
        source_facts={"similar_artist_mbid": ARTIST_ONE},
        fetched_at=now,
        expires_at=now + timedelta(days=7),
    )
