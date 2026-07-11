from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from music_recommender.agents.intent import (
    DiscoveryIntentValidationError,
    PolicySafeIntentParser,
)
from music_recommender.api.models import ProductRecommendationRequest


def test_policy_safe_intent_parser_sends_only_user_prompt_to_optional_model() -> None:
    received: list[str] = []

    def prompt_only_model(prompt: str) -> dict[str, Any]:
        received.append(prompt)
        return {"label": "late-night", "tags": ["trip hop", "downtempo"]}

    parser = PolicySafeIntentParser(
        llm_parser=prompt_only_model,
        parser_version="prompt-only-v1",
    )

    intent = parser.parse(
        "  Find me late-night music outside my usual rotation  ",
        adventure="adventurous",
        allow_explicit=False,
    )

    assert received == ["Find me late-night music outside my usual rotation"]
    assert intent.to_dict() == {
        "label": "late-night",
        "tags": ["trip hop", "downtempo"],
        "adventure": "adventurous",
        "allow_explicit": False,
        "parser_version": "prompt-only-v1",
    }


def test_policy_safe_intent_parser_rejects_extra_profile_or_catalog_fields() -> None:
    parser = PolicySafeIntentParser(
        llm_parser=lambda prompt: {
            "label": "unsafe",
            "tags": [],
            "spotify_profile": {"top_artists": [prompt]},
        }
    )

    with pytest.raises(DiscoveryIntentValidationError, match="only label and tags"):
        parser.parse(
            "Find unfamiliar jazz",
            adventure="balanced",
            allow_explicit=True,
        )


def test_deterministic_product_intent_is_bounded_and_transparent() -> None:
    parser = PolicySafeIntentParser()

    intent = parser.parse(
        "Calm focus music for studying",
        adventure="familiar",
        allow_explicit=True,
    )

    assert intent.label == "calm-focus"
    assert intent.tags == ("ambient", "downtempo", "instrumental")
    assert intent.parser_version == "deterministic-intent-v1"


def test_product_recommendation_contract_forbids_legacy_orchestration_and_profile_fields() -> None:
    payload = {
        "prompt": "Find unfamiliar jazz",
        "adventure": "balanced",
        "allow_explicit": True,
        "seed_ids": ["10000000-0000-0000-0000-000000000001"],
        "use_openai_agent": True,
        "create_playlist": True,
        "demo_user_id": "another-user",
        "liked_track_ids": ["spotify-track"],
        "catalog_run_id": "local-run",
    }

    with pytest.raises(ValidationError) as error:
        ProductRecommendationRequest.model_validate(payload)

    messages = str(error.value)
    for field in (
        "use_openai_agent",
        "create_playlist",
        "demo_user_id",
        "liked_track_ids",
        "catalog_run_id",
    ):
        assert field in messages
