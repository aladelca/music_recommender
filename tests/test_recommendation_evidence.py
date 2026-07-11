from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest

from music_recommender.agents.intent import DiscoveryIntent
from music_recommender.recommender.evidence import (
    EvidenceReason,
    EvidenceValidationError,
    build_recommendation_evidence,
    validate_recommendation_evidence,
)
from music_recommender.recommender.models import (
    DiscoveryScoreBreakdown,
    RankedDiscoveryCandidate,
)
from music_recommender.storage.protocols import CandidateEdgeRecord, MusicEntityRecord

SEED = "10000000-0000-0000-0000-000000000001"
RECORDING = "30000000-0000-0000-0000-000000000001"


def test_evidence_is_structured_visible_and_grounded_in_source_facts() -> None:
    candidate = ranked_candidate()
    intent = discovery_intent()

    evidence = build_recommendation_evidence(candidate, intent=intent)

    payload = evidence.to_dict()
    assert [reason["kind"] for reason in payload["reasons"]] == [
        "selected_seed",
        "source_edge",
        "tag_match",
        "listener_support",
        "source_diversity",
    ]
    assert {reason["source"] for reason in payload["reasons"]} == {
        "first_party",
        "listenbrainz",
    }
    assert payload["verifiable"] is True
    assert payload["evidence_version"] == "evidence-v1"
    assert "confidence" not in str(payload).casefold()
    assert "spotify" not in str(payload["reasons"]).casefold()


def test_sparse_evidence_declares_limitations_without_inventing_claims() -> None:
    candidate = ranked_candidate(sparse=True)

    evidence = build_recommendation_evidence(candidate, intent=discovery_intent())

    assert [reason.kind for reason in evidence.reasons] == ["selected_seed", "source_edge"]
    assert evidence.limitations == (
        "no_direct_prompt_tag_match",
        "listener_support_unavailable",
        "artist_credit_unavailable",
        "recording_title_pending",
        "explicit_status_unknown_until_spotify_mapping",
    )


def test_evidence_validator_rejects_unsupported_tag_or_source_claim() -> None:
    candidate = ranked_candidate()
    intent = discovery_intent()
    valid = build_recommendation_evidence(candidate, intent=intent)
    unsupported = EvidenceReason(
        kind="tag_match",
        source=cast(Any, "spotify"),
        text="Unsupported claim.",
        details={"tag": "metal"},
    )

    with pytest.raises(EvidenceValidationError, match="source"):
        validate_recommendation_evidence(
            replace(valid, reasons=valid.reasons + (unsupported,)),
            candidate=candidate,
            intent=intent,
        )


def ranked_candidate(*, sparse: bool = False) -> RankedDiscoveryCandidate:
    now = datetime(2030, 1, 1, tzinfo=UTC)
    entity = MusicEntityRecord(
        mbid=RECORDING,
        entity_type="recording",
        name=RECORDING if sparse else "Roads",
        artist_credit=(
            ()
            if sparse
            else (
                {
                    "mbid": "20000000-0000-0000-0000-000000000001",
                    "name": "Portishead",
                },
            )
        ),
        release_data={} if sparse else {"tags": ["trip hop", "downtempo"]},
        isrcs=(),
        source="listenbrainz",
        source_version="lb-core-v1",
        fetched_at=now,
        expires_at=now + timedelta(days=30),
    )
    primary = CandidateEdgeRecord(
        seed_mbid=SEED,
        candidate_recording_mbid=RECORDING,
        source_adapter="listenbrainz_artist_radio",
        algorithm_version="lb-core-v1",
        strength=None,
        listener_count=None if sparse else 1234,
        source_facts={} if sparse else {"tags": ["trip hop"]},
        fetched_at=now,
        expires_at=now + timedelta(days=7),
    )
    edges: tuple[CandidateEdgeRecord, ...] = (primary,)
    if not sparse:
        edges += (
            replace(
                primary,
                source_adapter="listenbrainz_tag_radio",
                strength=0.71,
                source_facts={"tags": ["trip hop", "downtempo"]},
            ),
        )
    return RankedDiscoveryCandidate(
        entity=entity,
        edges=edges,
        score=DiscoveryScoreBreakdown(
            prompt_tag_fit=1.0,
            seed_bridge_strength=0.71,
            discovery_value=0.4,
            evidence_quality=1.0,
            total=0.7,
        ),
        ranking_version="explicit-discovery-v1",
    )


def discovery_intent() -> DiscoveryIntent:
    return DiscoveryIntent(
        label="late-night",
        tags=("trip hop", "downtempo"),
        adventure="balanced",
        allow_explicit=True,
        parser_version="test-v1",
    )
