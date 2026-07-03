from __future__ import annotations

from typing import Any

from music_recommender.agents.intent import ParsedMoodIntent, parse_intent_with_agent


def test_parse_intent_with_agent_accepts_injected_runner_without_live_api() -> None:
    class FakeResult:
        final_output = ParsedMoodIntent.cheer_up_after_breakup(rationale="fake")

    class FakeRunner:
        @staticmethod
        def run_sync(*args: Any, **kwargs: Any) -> FakeResult:
            return FakeResult()

    intent = parse_intent_with_agent("cheer me up", runner=FakeRunner)

    assert intent.label == "cheer-up"
    assert intent.rationale == "fake"
