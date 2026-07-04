from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace

from music_recommender.ingest.parse_base import normalize_lookup_key
from music_recommender.recommender.models import (
    CatalogTrack,
    MoodIntent,
    RecommendationCandidate,
    ScoreBreakdown,
    UserTasteProfile,
)

MOOD_WEIGHT = 0.65
TASTE_WEIGHT = 0.20
NOVELTY_WEIGHT = 0.05
POPULARITY_WEIGHT = 0.10


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
