from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from music_recommender.agents.intent import DiscoveryIntent
from music_recommender.models import JsonDict
from music_recommender.recommender.models import RankedDiscoveryCandidate

EvidenceReasonKind = Literal[
    "selected_seed",
    "source_edge",
    "tag_match",
    "listener_support",
    "source_diversity",
]
EvidenceSource = Literal["first_party", "listenbrainz"]

_EVIDENCE_VERSION = "evidence-v1"
_REASON_SOURCES: dict[str, str] = {
    "selected_seed": "first_party",
    "source_edge": "listenbrainz",
    "tag_match": "listenbrainz",
    "listener_support": "listenbrainz",
    "source_diversity": "listenbrainz",
}
_REASON_DETAIL_KEYS: dict[str, set[str]] = {
    "selected_seed": {"seed_mbid"},
    "source_edge": {"seed_mbid", "source_adapter", "algorithm_version"},
    "tag_match": {"tag"},
    "listener_support": {"listener_count", "source_adapter"},
    "source_diversity": {"source_adapters"},
}


class EvidenceValidationError(ValueError):
    pass


@dataclass(frozen=True)
class EvidenceReason:
    kind: EvidenceReasonKind
    source: EvidenceSource
    text: str
    details: JsonDict

    def to_dict(self) -> JsonDict:
        return {
            "kind": self.kind,
            "source": self.source,
            "text": self.text,
            "details": dict(self.details),
        }


@dataclass(frozen=True)
class RecommendationEvidence:
    recording_mbid: str
    evidence_version: str
    reasons: tuple[EvidenceReason, ...]
    limitations: tuple[str, ...]

    @property
    def verifiable(self) -> bool:
        return bool(self.reasons)

    def to_dict(self) -> JsonDict:
        return {
            "recording_mbid": self.recording_mbid,
            "evidence_version": self.evidence_version,
            "verifiable": self.verifiable,
            "reasons": [reason.to_dict() for reason in self.reasons],
            "limitations": list(self.limitations),
        }


def build_recommendation_evidence(
    candidate: RankedDiscoveryCandidate,
    *,
    intent: DiscoveryIntent,
) -> RecommendationEvidence:
    edges = candidate.edges
    reasons: list[EvidenceReason] = []
    first_edge = edges[0] if edges else None
    if first_edge is not None:
        reasons.append(
            EvidenceReason(
                kind="selected_seed",
                source="first_party",
                text="Expanded from one of your selected MusicBrainz seeds.",
                details={"seed_mbid": first_edge.seed_mbid},
            )
        )
        reasons.append(
            EvidenceReason(
                kind="source_edge",
                source="listenbrainz",
                text=_source_edge_text(first_edge.source_adapter),
                details={
                    "seed_mbid": first_edge.seed_mbid,
                    "source_adapter": first_edge.source_adapter,
                    "algorithm_version": first_edge.algorithm_version,
                },
            )
        )

    matching_tags = _matching_tags(candidate, intent)
    if matching_tags:
        tag = matching_tags[0]
        reasons.append(
            EvidenceReason(
                kind="tag_match",
                source="listenbrainz",
                text=f"Matches the independent tag {tag!r} from your request.",
                details={"tag": tag},
            )
        )

    listener_edges = [edge for edge in edges if edge.listener_count is not None]
    if listener_edges:
        supported_edge = max(listener_edges, key=lambda edge: edge.listener_count or 0)
        listener_count = supported_edge.listener_count or 0
        reasons.append(
            EvidenceReason(
                kind="listener_support",
                source="listenbrainz",
                text=(f"ListenBrainz reports {listener_count:,} listens for this discovery edge."),
                details={
                    "listener_count": listener_count,
                    "source_adapter": supported_edge.source_adapter,
                },
            )
        )

    adapters = tuple(sorted({edge.source_adapter for edge in edges}))
    if len(adapters) > 1:
        reasons.append(
            EvidenceReason(
                kind="source_diversity",
                source="listenbrainz",
                text="Found through more than one independent discovery path.",
                details={"source_adapters": list(adapters)},
            )
        )

    limitations: list[str] = []
    if not matching_tags and intent.tags:
        limitations.append("no_direct_prompt_tag_match")
    if not listener_edges:
        limitations.append("listener_support_unavailable")
    if not candidate.entity.artist_credit:
        limitations.append("artist_credit_unavailable")
    if candidate.entity.name == candidate.entity.mbid:
        limitations.append("recording_title_pending")
    if "explicit" not in candidate.entity.release_data:
        limitations.append("explicit_status_unknown_until_spotify_mapping")

    evidence = RecommendationEvidence(
        recording_mbid=candidate.entity.mbid,
        evidence_version=_EVIDENCE_VERSION,
        reasons=tuple(reasons),
        limitations=tuple(limitations),
    )
    validate_recommendation_evidence(evidence, candidate=candidate, intent=intent)
    return evidence


def validate_recommendation_evidence(
    evidence: RecommendationEvidence,
    *,
    candidate: RankedDiscoveryCandidate,
    intent: DiscoveryIntent,
) -> None:
    if evidence.recording_mbid != candidate.entity.mbid:
        raise EvidenceValidationError("Evidence recording does not match the candidate.")
    if evidence.evidence_version != _EVIDENCE_VERSION:
        raise EvidenceValidationError("Evidence version is unsupported.")
    matching_tags = set(_matching_tags(candidate, intent))
    edge_keys = {
        (edge.seed_mbid, edge.source_adapter, edge.algorithm_version) for edge in candidate.edges
    }
    listener_keys = {
        (edge.listener_count, edge.source_adapter)
        for edge in candidate.edges
        if edge.listener_count is not None
    }
    adapters = tuple(sorted({edge.source_adapter for edge in candidate.edges}))
    seed_mbids = {edge.seed_mbid for edge in candidate.edges}
    for reason in evidence.reasons:
        if _REASON_SOURCES.get(reason.kind) != reason.source:
            raise EvidenceValidationError("Evidence reason source is unsupported.")
        if set(reason.details) != _REASON_DETAIL_KEYS[reason.kind]:
            raise EvidenceValidationError("Evidence reason details are unsupported.")
        if not reason.text or len(reason.text) > 500:
            raise EvidenceValidationError("Evidence reason text is invalid.")
        if reason.kind == "selected_seed":
            if reason.details["seed_mbid"] not in seed_mbids:
                raise EvidenceValidationError("Evidence selected seed is unsupported.")
        elif reason.kind == "source_edge":
            edge_key = (
                reason.details["seed_mbid"],
                reason.details["source_adapter"],
                reason.details["algorithm_version"],
            )
            if edge_key not in edge_keys:
                raise EvidenceValidationError("Evidence source edge is unsupported.")
        elif reason.kind == "tag_match":
            if reason.details["tag"] not in matching_tags:
                raise EvidenceValidationError("Evidence tag match is unsupported.")
        elif reason.kind == "listener_support":
            listener_key = (
                reason.details["listener_count"],
                reason.details["source_adapter"],
            )
            if listener_key not in listener_keys:
                raise EvidenceValidationError("Evidence listener support is unsupported.")
        elif reason.kind == "source_diversity" and (
            tuple(reason.details["source_adapters"]) != adapters or len(adapters) < 2
        ):
            raise EvidenceValidationError("Evidence source diversity is unsupported.")


def _matching_tags(
    candidate: RankedDiscoveryCandidate,
    intent: DiscoveryIntent,
) -> tuple[str, ...]:
    available: dict[str, str] = {}
    entity_tags = candidate.entity.release_data.get("tags", [])
    if isinstance(entity_tags, list):
        for value in entity_tags:
            if isinstance(value, str):
                available[value.casefold()] = value
    for edge in candidate.edges:
        edge_tags = edge.source_facts.get("tags", [])
        if isinstance(edge_tags, list):
            for value in edge_tags:
                if isinstance(value, str):
                    available[value.casefold()] = value
    return tuple(available[tag.casefold()] for tag in intent.tags if tag.casefold() in available)


def _source_edge_text(source_adapter: str) -> str:
    if source_adapter == "listenbrainz_artist_radio":
        return "ListenBrainz returned this recording through artist-radio discovery."
    if source_adapter == "listenbrainz_tag_radio":
        return "ListenBrainz returned this recording through tag-radio discovery."
    return "ListenBrainz returned this recording through an experimental discovery path."
