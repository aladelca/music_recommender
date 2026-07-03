from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from agents import Agent

from music_recommender.agents.guardrails import (
    validate_playlist_side_effect,
    validate_tracks_from_tool_output,
)
from music_recommender.agents.intent import (
    IntentParser,
    ParsedMoodIntent,
    parse_intent_deterministically,
)
from music_recommender.agents.tools import (
    AgentToolContext,
    build_agent_tools,
    rank_recommendations_payload,
)
from music_recommender.models import JsonDict
from music_recommender.recommender.models import (
    RecommendationCandidate,
    RecommenderCatalog,
    UserTasteProfile,
)
from music_recommender.recommender.scoring import rank_recommendations


@dataclass(frozen=True)
class PlaylistCandidate:
    name: str
    description: str
    track_ids: tuple[str, ...]

    def to_dict(self) -> JsonDict:
        return {
            "name": self.name,
            "description": self.description,
            "track_ids": list(self.track_ids),
        }


@dataclass(frozen=True)
class AgenticRecommendationResponse:
    session_id: str
    prompt: str
    intent: ParsedMoodIntent
    recommendations: tuple[RecommendationCandidate, ...]
    playlist_candidate: PlaylistCandidate | None = None

    def to_dict(self) -> JsonDict:
        payload: JsonDict = {
            "session_id": self.session_id,
            "prompt": self.prompt,
            "intent": self.intent.to_dict(),
            "recommendations": [
                _recommendation_to_payload(candidate) for candidate in self.recommendations
            ],
            "playlist_candidate": (
                self.playlist_candidate.to_dict() if self.playlist_candidate is not None else None
            ),
        }
        return payload


class AgenticRecommendationService:
    def __init__(
        self,
        *,
        catalog: RecommenderCatalog,
        profile: UserTasteProfile,
        intent_parser: IntentParser | None = None,
        session_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.catalog = catalog
        self.profile = profile
        self.intent_parser = intent_parser or parse_intent_deterministically
        self.session_id_factory = session_id_factory or (lambda: str(uuid.uuid4()))

    def recommend(
        self,
        *,
        prompt: str,
        limit: int,
        create_playlist: bool = False,
    ) -> AgenticRecommendationResponse:
        intent = self.intent_parser(prompt)
        context = AgentToolContext(catalog=self.catalog, profile=self.profile)
        tool_payload = rank_recommendations_payload(context, intent=intent, limit=limit)
        tool_track_ids = tuple(str(track_id) for track_id in tool_payload["track_ids"])
        recommendations = tuple(
            rank_recommendations(
                self.catalog.tracks,
                intent=intent.to_domain(),
                profile=self.profile,
                limit=limit,
            )
        )
        final_track_ids = tuple(candidate.track.id for candidate in recommendations)
        validate_tracks_from_tool_output(
            tool_track_ids=tool_track_ids,
            final_track_ids=final_track_ids,
        )
        playlist_candidate = (
            PlaylistCandidate(
                name=_playlist_name(intent),
                description=f"Generated from prompt: {prompt}",
                track_ids=final_track_ids,
            )
            if create_playlist
            else None
        )
        validate_playlist_side_effect(
            create_playlist_requested=create_playlist,
            playlist_created=playlist_candidate is not None,
        )
        return AgenticRecommendationResponse(
            session_id=self.session_id_factory(),
            prompt=prompt,
            intent=intent,
            recommendations=recommendations,
            playlist_candidate=playlist_candidate,
        )


def build_recommendation_orchestrator_agent(
    *,
    context: AgentToolContext,
    model: str | None = None,
) -> Agent[Any]:
    return Agent(
        name="Music recommendation orchestrator",
        model=model,
        instructions=(
            "Use the provided tools to load profile/catalog data and rank recommendations. "
            "Never invent songs. Final track IDs must come from rank_catalog_recommendations. "
            "Do not create playlists unless the request explicitly asks for playlist creation."
        ),
        tools=build_agent_tools(context),
    )


def _playlist_name(intent: ParsedMoodIntent) -> str:
    return f"Music Recommender - {intent.label}"


def _recommendation_to_payload(candidate: RecommendationCandidate) -> JsonDict:
    track = candidate.track
    score = candidate.score
    return {
        "track": {
            "id": track.id,
            "name": track.name,
            "artist_names": list(track.artist_names),
            "explicit": track.explicit,
            "popularity": track.popularity,
            "spotify_url": track.spotify_url,
        },
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
