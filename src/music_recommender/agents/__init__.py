from __future__ import annotations

from typing import Any

from music_recommender.agents.intent import ParsedMoodIntent

__all__ = [
    "AgenticRecommendationResponse",
    "AgenticRecommendationService",
    "ParsedMoodIntent",
]


def __getattr__(name: str) -> Any:
    if name in {"AgenticRecommendationResponse", "AgenticRecommendationService"}:
        from music_recommender.agents.orchestrator import (
            AgenticRecommendationResponse,
            AgenticRecommendationService,
        )

        return {
            "AgenticRecommendationResponse": AgenticRecommendationResponse,
            "AgenticRecommendationService": AgenticRecommendationService,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
