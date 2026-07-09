from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

from agents import Agent, Runner

from music_recommender.agents.guardrails import (
    AgentGuardrailError,
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
class OrchestratedRecommendationOutput:
    track_ids: tuple[str, ...]
    playlist_created: bool = False
    rationale: str | None = None

    def to_dict(self) -> JsonDict:
        payload = asdict(self)
        payload["track_ids"] = list(self.track_ids)
        return payload


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
        agent_runner: Any = Runner,
        agent_model: str | None = None,
        session_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.catalog = catalog
        self.profile = profile
        self.intent_parser = intent_parser or parse_intent_deterministically
        self.agent_runner = agent_runner
        self.agent_model = agent_model
        self.session_id_factory = session_id_factory or (lambda: str(uuid.uuid4()))

    def recommend(
        self,
        *,
        prompt: str,
        limit: int,
        create_playlist: bool = False,
        playlist_name: str | None = None,
        use_agent_orchestrator: bool = False,
    ) -> AgenticRecommendationResponse:
        intent = self.intent_parser(prompt)
        context = AgentToolContext(catalog=self.catalog, profile=self.profile)
        if use_agent_orchestrator:
            return self._recommend_with_agent(
                prompt=prompt,
                intent=intent,
                context=context,
                limit=limit,
                create_playlist=create_playlist,
                playlist_name=playlist_name,
            )
        return self._recommend_deterministically(
            prompt=prompt,
            intent=intent,
            context=context,
            limit=limit,
            create_playlist=create_playlist,
            playlist_name=playlist_name,
        )

    def _recommend_deterministically(
        self,
        *,
        prompt: str,
        intent: ParsedMoodIntent,
        context: AgentToolContext,
        limit: int,
        create_playlist: bool,
        playlist_name: str | None,
    ) -> AgenticRecommendationResponse:
        tool_payload = rank_recommendations_payload(context, intent=intent, limit=limit)
        final_track_ids = validate_tracks_from_tool_output(
            tool_track_ids=(str(track_id) for track_id in tool_payload["track_ids"]),
            final_track_ids=context.last_ranked_track_ids,
        )
        recommendations = _recommendations_for_track_ids(context, final_track_ids)
        playlist_candidate = (
            PlaylistCandidate(
                name=_playlist_name(intent, override=playlist_name),
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

    def _recommend_with_agent(
        self,
        *,
        prompt: str,
        intent: ParsedMoodIntent,
        context: AgentToolContext,
        limit: int,
        create_playlist: bool,
        playlist_name: str | None,
    ) -> AgenticRecommendationResponse:
        agent = build_recommendation_orchestrator_agent(
            context=context,
            model=self.agent_model,
        )
        result = self.agent_runner.run_sync(
            agent,
            _orchestrator_input(
                prompt=prompt,
                intent=intent,
                limit=limit,
                create_playlist=create_playlist,
            ),
            context=context,
            max_turns=6,
        )
        output = _coerce_orchestrated_output(result.final_output)
        if not context.rank_tool_called:
            raise AgentGuardrailError("Agent did not call rank_catalog_recommendations.")
        final_track_ids = validate_tracks_from_tool_output(
            tool_track_ids=context.last_ranked_track_ids,
            final_track_ids=output.track_ids,
        )
        recommendations = _recommendations_for_track_ids(context, final_track_ids)
        validate_playlist_side_effect(
            create_playlist_requested=create_playlist,
            playlist_created=output.playlist_created,
        )
        playlist_candidate = (
            PlaylistCandidate(
                name=_playlist_name(intent, override=playlist_name),
                description=f"Generated from prompt: {prompt}",
                track_ids=final_track_ids,
            )
            if create_playlist
            else None
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
        output_type=OrchestratedRecommendationOutput,
    )


def _orchestrator_input(
    *,
    prompt: str,
    intent: ParsedMoodIntent,
    limit: int,
    create_playlist: bool,
) -> str:
    return (
        "Create catalog-backed music recommendations.\n"
        f"User prompt: {prompt}\n"
        f"Parsed intent: {intent.to_dict()}\n"
        f"Limit: {limit}\n"
        f"Playlist requested: {create_playlist}\n"
        "Call rank_catalog_recommendations before returning final track_ids."
    )


def _coerce_orchestrated_output(output: Any) -> OrchestratedRecommendationOutput:
    if isinstance(output, OrchestratedRecommendationOutput):
        return output
    if isinstance(output, dict):
        track_ids = output.get("track_ids", ())
        parsed_track_ids: tuple[str, ...]
        if isinstance(track_ids, str):
            parsed_track_ids = (track_ids,)
        elif isinstance(track_ids, list | tuple):
            parsed_track_ids = tuple(str(track_id) for track_id in track_ids)
        else:
            parsed_track_ids = ()
        return OrchestratedRecommendationOutput(
            track_ids=parsed_track_ids,
            playlist_created=bool(output.get("playlist_created", False)),
            rationale=str(output["rationale"]) if output.get("rationale") is not None else None,
        )
    raise TypeError("Recommendation orchestrator returned an unsupported output type.")


def _recommendations_for_track_ids(
    context: AgentToolContext,
    track_ids: tuple[str, ...],
) -> tuple[RecommendationCandidate, ...]:
    candidates_by_id = {
        candidate.track.id: candidate for candidate in context.last_ranked_candidates
    }
    missing = [track_id for track_id in track_ids if track_id not in candidates_by_id]
    if missing:
        raise AgentGuardrailError(
            "Agent output referenced tracks missing from rank tool candidates: "
            + ", ".join(missing)
        )
    return tuple(candidates_by_id[track_id] for track_id in track_ids)


def _playlist_name(intent: ParsedMoodIntent, *, override: str | None = None) -> str:
    return override or f"Music Recommender - {intent.label}"


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
