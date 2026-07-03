from __future__ import annotations

from collections.abc import Iterable


class AgentGuardrailError(ValueError):
    pass


def validate_tracks_from_tool_output(
    *,
    tool_track_ids: Iterable[str],
    final_track_ids: Iterable[str],
) -> tuple[str, ...]:
    allowed_ids = set(tool_track_ids)
    ordered_final_ids = tuple(final_track_ids)
    invented_ids = [track_id for track_id in ordered_final_ids if track_id not in allowed_ids]
    if invented_ids:
        raise AgentGuardrailError(
            "Agent output included tracks outside tool results: " + ", ".join(invented_ids)
        )
    return ordered_final_ids


def validate_playlist_side_effect(
    *,
    create_playlist_requested: bool,
    playlist_created: bool,
) -> None:
    if playlist_created and not create_playlist_requested:
        raise AgentGuardrailError("Playlist creation must be explicitly requested.")
