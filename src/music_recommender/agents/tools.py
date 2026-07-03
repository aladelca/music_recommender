from __future__ import annotations

from dataclasses import dataclass

from agents import Tool, function_tool

from music_recommender.agents.intent import ParsedMoodIntent
from music_recommender.models import JsonDict
from music_recommender.recommender.models import (
    CatalogTrack,
    RecommendationCandidate,
    RecommenderCatalog,
    UserTasteProfile,
)
from music_recommender.recommender.scoring import rank_recommendations


@dataclass(frozen=True)
class AgentToolContext:
    catalog: RecommenderCatalog
    profile: UserTasteProfile


def load_user_profile_payload(context: AgentToolContext) -> JsonDict:
    profile = context.profile
    return {
        "user_id": profile.user_id,
        "liked_track_ids": list(profile.liked_track_ids),
        "known_track_ids": list(profile.known_track_ids),
        "liked_artist_names": list(profile.liked_artist_names),
        "blocked_artist_names": list(profile.blocked_artist_names),
        "artist_affinity": profile.artist_affinity or {},
        "track_affinity": profile.track_affinity or {},
    }


def load_catalog_candidates_payload(context: AgentToolContext, *, limit: int = 50) -> JsonDict:
    bounded_limit = max(0, min(limit, 100))
    tracks = list(context.catalog.tracks[:bounded_limit])
    return {
        "count": len(tracks),
        "tracks": [_catalog_track_summary(track) for track in tracks],
    }


def rank_recommendations_payload(
    context: AgentToolContext,
    *,
    intent: ParsedMoodIntent,
    limit: int,
    max_tracks_per_artist: int = 2,
) -> JsonDict:
    ranked = rank_recommendations(
        context.catalog.tracks,
        intent=intent.to_domain(),
        profile=context.profile,
        limit=limit,
        max_tracks_per_artist=max_tracks_per_artist,
    )
    tracks = [_recommendation_to_payload(candidate) for candidate in ranked]
    return {
        "intent": intent.to_dict(),
        "track_ids": [track["track"]["id"] for track in tracks],
        "tracks": tracks,
    }


def build_agent_tools(context: AgentToolContext) -> list[Tool]:
    @function_tool
    def load_user_profile() -> JsonDict:
        """Load the current demo user's music taste profile."""
        return load_user_profile_payload(context)

    @function_tool
    def load_catalog_candidates(limit: int = 50) -> JsonDict:
        """Load a bounded summary of available catalog tracks."""
        return load_catalog_candidates_payload(context, limit=limit)

    @function_tool
    def rank_catalog_recommendations(
        label: str,
        target_valence: float,
        target_energy: float,
        target_danceability: float,
        limit: int = 10,
        allow_explicit: bool = True,
        blocked_artist_names: list[str] | None = None,
    ) -> JsonDict:
        """Rank catalog-backed recommendations for a parsed mood intent."""
        intent = ParsedMoodIntent(
            label=label,
            target_valence=target_valence,
            target_energy=target_energy,
            target_danceability=target_danceability,
            allow_explicit=allow_explicit,
            blocked_artist_names=tuple(blocked_artist_names or ()),
        )
        return rank_recommendations_payload(context, intent=intent, limit=limit)

    return [load_user_profile, load_catalog_candidates, rank_catalog_recommendations]


def _catalog_track_summary(track: CatalogTrack) -> JsonDict:
    return {
        "id": track.id,
        "name": track.name,
        "artist_names": list(track.artist_names),
        "explicit": track.explicit,
        "popularity": track.popularity,
        "spotify_url": track.spotify_url,
    }


def _recommendation_to_payload(candidate: RecommendationCandidate) -> JsonDict:
    track = candidate.track
    score = candidate.score
    return {
        "id": track.id,
        "name": track.name,
        "track": _catalog_track_summary(track),
        "score": {
            "mood_fit": score.mood_fit,
            "taste_affinity": score.taste_affinity,
            "novelty_bonus": score.novelty_bonus,
            "popularity_prior": score.popularity_prior,
            "diversity_penalty": score.diversity_penalty,
            "total": score.total,
        },
        "explanation": candidate.explanation,
    }
