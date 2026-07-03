from __future__ import annotations

import json
from typing import Any

import pytest

from music_recommender.agents.guardrails import AgentGuardrailError
from music_recommender.agents.intent import ParsedMoodIntent
from music_recommender.agents.orchestrator import (
    AgenticRecommendationService,
    OrchestratedRecommendationOutput,
)
from music_recommender.agents.tools import rank_recommendations_payload
from music_recommender.recommender.models import (
    AudioFeatures,
    CatalogTrack,
    RecommenderCatalog,
    UserTasteProfile,
)


def test_agentic_recommendation_service_returns_structured_ranked_tracks() -> None:
    service = AgenticRecommendationService(
        catalog=RecommenderCatalog(
            tracks=(
                catalog_track("sunny", "Sunny Recovery", "Dua Lipa", valence=0.94),
                catalog_track("sad", "Sad Ballad", "Dua Lipa", valence=0.1),
            )
        ),
        profile=UserTasteProfile(user_id="demo", liked_artist_names=("Dua Lipa",)),
        intent_parser=lambda prompt: ParsedMoodIntent.cheer_up_after_breakup(
            rationale=f"Parsed from: {prompt}",
        ),
    )

    response = service.recommend(
        prompt="I just broke up with my girlfriend and I want songs to cheer me up",
        limit=2,
    )

    assert response.intent.label == "cheer-up"
    assert [candidate.track.id for candidate in response.recommendations] == ["sunny", "sad"]
    assert response.playlist_candidate is None
    payload = response.to_dict()
    assert payload["recommendations"][0]["track"]["id"] == "sunny"
    json.dumps(payload)


def test_agentic_recommendation_service_exposes_playlist_candidate_only_when_requested() -> None:
    service = AgenticRecommendationService(
        catalog=RecommenderCatalog(
            tracks=(catalog_track("sunny", "Sunny Recovery", "Dua Lipa", valence=0.94),)
        ),
        profile=UserTasteProfile(user_id="demo"),
        intent_parser=lambda prompt: ParsedMoodIntent.cheer_up_after_breakup(),
    )

    response = service.recommend(
        prompt="make me a playlist to cheer up",
        limit=1,
        create_playlist=True,
    )

    assert response.playlist_candidate is not None
    assert response.playlist_candidate.track_ids == ("sunny",)


def test_agentic_recommendation_service_can_run_tool_backed_agent_orchestrator() -> None:
    class FakeResult:
        final_output = OrchestratedRecommendationOutput(
            track_ids=("sunny",),
            rationale="Used rank tool output.",
        )

    class FakeRunner:
        @staticmethod
        def run_sync(starting_agent: Any, input: str, **kwargs: Any) -> FakeResult:
            context = kwargs["context"]
            assert [tool.name for tool in starting_agent.tools] == [
                "load_user_profile",
                "load_catalog_candidates",
                "rank_catalog_recommendations",
            ]
            assert "Call rank_catalog_recommendations" in input
            rank_recommendations_payload(
                context,
                intent=ParsedMoodIntent.cheer_up_after_breakup(),
                limit=2,
            )
            return FakeResult()

    service = AgenticRecommendationService(
        catalog=RecommenderCatalog(
            tracks=(
                catalog_track("sunny", "Sunny Recovery", "Dua Lipa", valence=0.94),
                catalog_track("sad", "Sad Ballad", "Dua Lipa", valence=0.1),
            )
        ),
        profile=UserTasteProfile(user_id="demo"),
        intent_parser=lambda prompt: ParsedMoodIntent.cheer_up_after_breakup(),
        agent_runner=FakeRunner,
    )

    response = service.recommend(
        prompt="cheer me up",
        limit=2,
        use_agent_orchestrator=True,
    )

    assert [candidate.track.id for candidate in response.recommendations] == ["sunny"]


def test_agentic_recommendation_service_rejects_agent_tracks_outside_tool_output() -> None:
    class FakeResult:
        final_output = OrchestratedRecommendationOutput(track_ids=("invented",))

    class FakeRunner:
        @staticmethod
        def run_sync(starting_agent: Any, input: str, **kwargs: Any) -> FakeResult:
            rank_recommendations_payload(
                kwargs["context"],
                intent=ParsedMoodIntent.cheer_up_after_breakup(),
                limit=1,
            )
            return FakeResult()

    service = AgenticRecommendationService(
        catalog=RecommenderCatalog(
            tracks=(catalog_track("sunny", "Sunny Recovery", "Dua Lipa", valence=0.94),)
        ),
        profile=UserTasteProfile(user_id="demo"),
        intent_parser=lambda prompt: ParsedMoodIntent.cheer_up_after_breakup(),
        agent_runner=FakeRunner,
    )

    with pytest.raises(AgentGuardrailError, match="invented"):
        service.recommend(
            prompt="cheer me up",
            limit=1,
            use_agent_orchestrator=True,
        )


def catalog_track(
    track_id: str,
    name: str,
    artist: str,
    *,
    valence: float,
) -> CatalogTrack:
    return CatalogTrack(
        id=track_id,
        name=name,
        artist_names=(artist,),
        primary_artist_name=artist,
        explicit=False,
        popularity=80,
        spotify_url=f"https://open.spotify.com/track/{track_id}",
        audio_features=AudioFeatures(
            spotify_track_id=track_id,
            danceability=0.82,
            energy=0.8,
            valence=valence,
        ),
    )
