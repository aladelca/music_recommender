from __future__ import annotations

import pytest

from music_recommender.agents.guardrails import (
    AgentGuardrailError,
    validate_playlist_side_effect,
    validate_tracks_from_tool_output,
)


def test_validate_tracks_from_tool_output_rejects_invented_tracks() -> None:
    with pytest.raises(AgentGuardrailError, match="invented-track"):
        validate_tracks_from_tool_output(
            tool_track_ids=("catalog-track",),
            final_track_ids=("catalog-track", "invented-track"),
        )


def test_validate_tracks_from_tool_output_preserves_order_for_valid_tracks() -> None:
    assert validate_tracks_from_tool_output(
        tool_track_ids=("track-1", "track-2"),
        final_track_ids=("track-2", "track-1"),
    ) == ("track-2", "track-1")


def test_validate_playlist_side_effect_requires_explicit_request() -> None:
    with pytest.raises(AgentGuardrailError, match="explicitly requested"):
        validate_playlist_side_effect(create_playlist_requested=False, playlist_created=True)

    validate_playlist_side_effect(create_playlist_requested=True, playlist_created=True)
