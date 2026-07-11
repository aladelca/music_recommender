from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import replace

from music_recommender.agents.intent import DiscoveryIntent
from music_recommender.normalization import normalize_lookup_key
from music_recommender.recommender.models import (
    CatalogTrack,
    DiscoveryRankingPreferences,
    DiscoveryScoreBreakdown,
    MoodIntent,
    RankedDiscoveryCandidate,
    RecommendationCandidate,
    ScoreBreakdown,
    UserTasteProfile,
)
from music_recommender.storage.protocols import CandidateEdgeRecord, MusicEntityRecord

MOOD_WEIGHT = 0.65
TASTE_WEIGHT = 0.20
NOVELTY_WEIGHT = 0.05
POPULARITY_WEIGHT = 0.10
DISCOVERY_RANKING_VERSION = "explicit-discovery-v1"

_ADVENTURE_WEIGHTS = {
    "familiar": (0.40, 0.10),
    "balanced": (0.30, 0.20),
    "adventurous": (0.20, 0.30),
}


def rank_discovery_candidates(
    edges: Iterable[CandidateEdgeRecord],
    *,
    entities: Mapping[str, MusicEntityRecord],
    intent: DiscoveryIntent,
    selected_seed_mbids: tuple[str, ...],
    preferences: DiscoveryRankingPreferences | None = None,
    limit: int = 50,
    max_tracks_per_artist: int = 1,
) -> list[RankedDiscoveryCandidate]:
    if not 1 <= limit <= 50:
        raise ValueError("Discovery ranking limit must be between 1 and 50.")
    if not 1 <= max_tracks_per_artist <= 5:
        raise ValueError("max_tracks_per_artist must be between 1 and 5.")
    resolved_preferences = preferences or DiscoveryRankingPreferences()
    blocked_recordings = set(resolved_preferences.blocked_recording_mbids)
    blocked_artists = set(resolved_preferences.blocked_artist_mbids)
    selected_seeds = set(selected_seed_mbids)
    edges_by_recording: dict[str, list[CandidateEdgeRecord]] = {}
    for edge in edges:
        if edge.seed_mbid not in selected_seeds:
            continue
        edges_by_recording.setdefault(edge.candidate_recording_mbid, []).append(edge)

    scored: list[RankedDiscoveryCandidate] = []
    for recording_mbid, candidate_edges in edges_by_recording.items():
        entity = entities.get(recording_mbid)
        if entity is None or entity.entity_type != "recording":
            continue
        if recording_mbid in selected_seeds or recording_mbid in blocked_recordings:
            continue
        artist_mbids = _artist_mbids(entity)
        if blocked_artists.intersection(artist_mbids):
            continue
        if not intent.allow_explicit and entity.release_data.get("explicit") is True:
            continue
        ordered_edges = tuple(
            sorted(
                candidate_edges,
                key=lambda edge: (
                    edge.source_adapter,
                    edge.seed_mbid,
                    edge.candidate_recording_mbid,
                ),
            )
        )
        breakdown = _discovery_score(entity, ordered_edges, intent)
        scored.append(
            RankedDiscoveryCandidate(
                entity=entity,
                edges=ordered_edges,
                score=breakdown,
                ranking_version=DISCOVERY_RANKING_VERSION,
            )
        )

    ordered = sorted(
        scored,
        key=lambda candidate: (
            -candidate.score.total,
            -candidate.score.evidence_quality,
            candidate.entity.mbid,
        ),
    )
    selected: list[RankedDiscoveryCandidate] = []
    artist_counts: dict[str, int] = {}
    for candidate in ordered:
        artist_key = _primary_artist_mbid(candidate.entity)
        if artist_counts.get(artist_key, 0) >= max_tracks_per_artist:
            continue
        selected.append(candidate)
        artist_counts[artist_key] = artist_counts.get(artist_key, 0) + 1
        if len(selected) == limit:
            break
    return selected


def _discovery_score(
    entity: MusicEntityRecord,
    edges: tuple[CandidateEdgeRecord, ...],
    intent: DiscoveryIntent,
) -> DiscoveryScoreBreakdown:
    prompt_tag_fit = _prompt_tag_fit(entity, edges, intent)
    seed_bridge_strength = _seed_bridge_strength(edges)
    discovery_value = _discovery_value(edges)
    evidence_quality = _evidence_quality(entity, edges)
    bridge_weight, discovery_weight = _ADVENTURE_WEIGHTS[intent.adventure]
    total = (
        (0.35 * prompt_tag_fit)
        + (bridge_weight * seed_bridge_strength)
        + (discovery_weight * discovery_value)
        + (0.15 * evidence_quality)
    )
    return DiscoveryScoreBreakdown(
        prompt_tag_fit=_clamp(prompt_tag_fit),
        seed_bridge_strength=_clamp(seed_bridge_strength),
        discovery_value=_clamp(discovery_value),
        evidence_quality=_clamp(evidence_quality),
        total=_clamp(total),
    )


def _prompt_tag_fit(
    entity: MusicEntityRecord,
    edges: tuple[CandidateEdgeRecord, ...],
    intent: DiscoveryIntent,
) -> float:
    if not intent.tags:
        return 0.5
    candidate_tags = {
        str(tag).casefold() for tag in entity.release_data.get("tags", []) if isinstance(tag, str)
    }
    for edge in edges:
        values = edge.source_facts.get("tags", [])
        if isinstance(values, list):
            candidate_tags.update(str(tag).casefold() for tag in values if isinstance(tag, str))
    intended_tags = {tag.casefold() for tag in intent.tags}
    return len(candidate_tags.intersection(intended_tags)) / len(intended_tags)


def _seed_bridge_strength(edges: tuple[CandidateEdgeRecord, ...]) -> float:
    strengths: list[float] = []
    for edge in edges:
        if edge.strength is not None:
            strengths.append(edge.strength)
        elif edge.source_facts.get("similar_artist_mbid"):
            strengths.append(0.6)
        else:
            strengths.append(0.5)
    base = max(strengths, default=0.0)
    adapter_bonus = max(len({edge.source_adapter for edge in edges}) - 1, 0) * 0.05
    return _clamp(base + adapter_bonus)


def _discovery_value(edges: tuple[CandidateEdgeRecord, ...]) -> float:
    listener_counts = [
        edge.listener_count
        for edge in edges
        if edge.listener_count is not None and edge.listener_count >= 0
    ]
    if not listener_counts:
        return 0.5
    listener_count = min(listener_counts)
    popularity_proxy = math.log1p(listener_count) / math.log1p(1_000_000)
    return 1.0 - _clamp(popularity_proxy)


def _evidence_quality(
    entity: MusicEntityRecord,
    edges: tuple[CandidateEdgeRecord, ...],
) -> float:
    quality = 0.0
    if entity.name and entity.name != entity.mbid:
        quality += 0.25
    if entity.artist_credit:
        quality += 0.20
    if entity.release_data.get("tags"):
        quality += 0.15
    if edges:
        quality += 0.20
    if any(edge.strength is not None or edge.listener_count is not None for edge in edges):
        quality += 0.20
    return _clamp(quality)


def _artist_mbids(entity: MusicEntityRecord) -> set[str]:
    return {
        str(credit["mbid"])
        for credit in entity.artist_credit
        if isinstance(credit.get("mbid"), str)
    }


def _primary_artist_mbid(entity: MusicEntityRecord) -> str:
    artists = _artist_mbids(entity)
    return min(artists) if artists else entity.mbid


def rank_recommendations(
    tracks: Iterable[CatalogTrack],
    *,
    intent: MoodIntent,
    profile: UserTasteProfile,
    limit: int,
    max_tracks_per_artist: int = 2,
) -> list[RecommendationCandidate]:
    if limit <= 0:
        return []

    blocked_artists = _normalized_set(intent.blocked_artist_names) | _normalized_set(
        profile.blocked_artist_names
    )
    seen_track_ids: set[str] = set()
    candidates: list[RecommendationCandidate] = []
    for track in tracks:
        if track.id in seen_track_ids:
            continue
        seen_track_ids.add(track.id)
        if _is_blocked(track, intent=intent, blocked_artists=blocked_artists):
            continue
        score = _score_track(track, intent=intent, profile=profile, diversity_penalty=0.0)
        candidates.append(
            RecommendationCandidate(
                track=track,
                score=score,
                explanation=_explain(track, intent=intent, profile=profile, score=score),
            )
        )

    selected: list[RecommendationCandidate] = []
    artist_counts: dict[str, int] = {}
    remaining = sorted(candidates, key=lambda candidate: candidate.score.total, reverse=True)
    while remaining and len(selected) < limit:
        adjusted = [
            _with_diversity_penalty(candidate, artist_counts)
            for candidate in remaining
            if artist_counts.get(_primary_artist_key(candidate.track), 0) < max_tracks_per_artist
        ]
        if not adjusted:
            break
        best = max(adjusted, key=lambda candidate: candidate.score.total)
        selected.append(best)
        artist_key = _primary_artist_key(best.track)
        artist_counts[artist_key] = artist_counts.get(artist_key, 0) + 1
        remaining = [candidate for candidate in remaining if candidate.track.id != best.track.id]
    return selected


def _score_track(
    track: CatalogTrack,
    *,
    intent: MoodIntent,
    profile: UserTasteProfile,
    diversity_penalty: float,
) -> ScoreBreakdown:
    mood = _mood_fit(track, intent)
    taste = _taste_affinity(track, profile)
    novelty = 0.0 if track.id in set(profile.known_track_ids) else 1.0
    popularity = _clamp((track.popularity or 0) / 100.0)
    total = (
        (MOOD_WEIGHT * mood)
        + (TASTE_WEIGHT * taste)
        + (NOVELTY_WEIGHT * novelty)
        + (POPULARITY_WEIGHT * popularity)
        - diversity_penalty
    )
    return ScoreBreakdown(
        mood_fit=mood,
        taste_affinity=taste,
        novelty_bonus=novelty,
        popularity_prior=popularity,
        diversity_penalty=diversity_penalty,
        total=_clamp(total),
    )


def _mood_fit(track: CatalogTrack, intent: MoodIntent) -> float:
    features = track.audio_features
    values: list[float] = []
    if features is not None:
        if features.valence is not None:
            values.append(_target_fit(features.valence, intent.target_valence))
        if features.energy is not None:
            values.append(_target_fit(features.energy, intent.target_energy))
        if features.danceability is not None:
            values.append(_target_fit(features.danceability, intent.target_danceability))
    if track.lyrics_positive_score is not None:
        values.append(_clamp(track.lyrics_positive_score))
    if track.lyrics_negative_score is not None:
        values.append(1.0 - _clamp(track.lyrics_negative_score))
    if not values:
        return 0.0
    return sum(values) / len(values)


def _target_fit(value: float | None, target: float) -> float:
    if value is None:
        return 0.5
    return 1.0 - min(abs(_clamp(value) - _clamp(target)), 1.0)


def _taste_affinity(track: CatalogTrack, profile: UserTasteProfile) -> float:
    score = 0.0
    normalized_artists = _normalized_set(track.artist_names)
    normalized_artists.add(normalize_lookup_key(track.primary_artist_name or ""))
    liked_artists = _normalized_set(profile.liked_artist_names)
    if normalized_artists & liked_artists:
        score += 0.55
    if track.id in set(profile.liked_track_ids):
        score += 0.35
    if profile.artist_affinity:
        score += (
            max(
                (
                    _clamp(value)
                    for artist, value in profile.artist_affinity.items()
                    if normalize_lookup_key(artist) in normalized_artists
                ),
                default=0.0,
            )
            * 0.35
        )
    if profile.track_affinity and track.id in profile.track_affinity:
        score += _clamp(profile.track_affinity[track.id]) * 0.40
    if track.max_implicit_rating is not None:
        score += _clamp(track.max_implicit_rating / 5.0) * 0.20
    return _clamp(score)


def _is_blocked(
    track: CatalogTrack,
    *,
    intent: MoodIntent,
    blocked_artists: set[str],
) -> bool:
    if track.explicit and not intent.allow_explicit:
        return True
    track_artists = _normalized_set(track.artist_names)
    if track.primary_artist_name:
        track_artists.add(normalize_lookup_key(track.primary_artist_name))
    return bool(track_artists & blocked_artists)


def _with_diversity_penalty(
    candidate: RecommendationCandidate,
    artist_counts: dict[str, int],
) -> RecommendationCandidate:
    penalty = min(artist_counts.get(_primary_artist_key(candidate.track), 0) * 0.15, 0.45)
    if penalty == candidate.score.diversity_penalty:
        return candidate
    score = replace(
        candidate.score,
        diversity_penalty=penalty,
        total=_clamp(candidate.score.total + candidate.score.diversity_penalty - penalty),
    )
    return replace(
        candidate,
        score=score,
        explanation=_explanation_with_score(candidate.explanation, score),
    )


def _explain(
    track: CatalogTrack,
    *,
    intent: MoodIntent,
    profile: UserTasteProfile,
    score: ScoreBreakdown,
) -> str:
    parts = [f"Strong {intent.label} mood fit"]
    liked_artists = _normalized_set(profile.liked_artist_names)
    matching_artists = [
        artist for artist in track.artist_names if normalize_lookup_key(artist) in liked_artists
    ]
    if matching_artists:
        parts.append(f"matches your taste for {matching_artists[0]}")
    if score.novelty_bonus > 0:
        parts.append("adds some novelty")
    return _explanation_with_score("; ".join(parts), score)


def _explanation_with_score(explanation: str, score: ScoreBreakdown) -> str:
    base = explanation.split(" score=")[0]
    return f"{base} score={score.total:.2f}"


def _primary_artist_key(track: CatalogTrack) -> str:
    return normalize_lookup_key(
        track.primary_artist_name or (track.artist_names[0] if track.artist_names else "")
    )


def _normalized_set(values: Iterable[str]) -> set[str]:
    normalized: set[str] = set()
    for value in values:
        key = normalize_lookup_key(value)
        if key:
            normalized.add(key)
    return normalized


def _clamp(value: float) -> float:
    return max(0.0, min(value, 1.0))
