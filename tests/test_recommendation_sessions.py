from __future__ import annotations

import json
from pathlib import Path

from music_recommender.recommender.sessions import (
    JsonRecommendationSessionStore,
    PlaylistResult,
    RecommendationSession,
)


def test_json_recommendation_session_store_round_trips_session(tmp_path: Path) -> None:
    store = JsonRecommendationSessionStore(tmp_path / "sessions.json")
    session = build_session()

    store.put(session)

    loaded = store.get("session-1")
    assert loaded is not None
    assert loaded.session_id == "session-1"
    assert loaded.user_id == "12175364859"
    assert loaded.recommended_track_ids == ("sunny", "dance")
    assert loaded.recommendations[0]["track"]["id"] == "sunny"
    assert loaded.catalog_run_id == "catalog-run"
    assert loaded.interaction_run_id == "interaction-run"


def test_json_recommendation_session_store_tolerates_unknown_fields(tmp_path: Path) -> None:
    path = tmp_path / "sessions.json"
    store = JsonRecommendationSessionStore(path)
    store.put(build_session())
    payload = json.loads(path.read_text())
    payload["session-1"]["unknown_future_field"] = {"ignored": True}
    path.write_text(json.dumps(payload))

    loaded = store.get("session-1")

    assert loaded is not None
    assert loaded.session_id == "session-1"
    assert loaded.recommended_track_ids == ("sunny", "dance")


def test_recommendation_session_identifies_invalid_requested_tracks() -> None:
    session = build_session()

    assert session.invalid_track_ids(("dance", "sunny")) == ()
    assert session.invalid_track_ids(("sunny", "invented")) == ("invented",)


def test_json_recommendation_session_store_updates_playlist_result(tmp_path: Path) -> None:
    store = JsonRecommendationSessionStore(tmp_path / "sessions.json")
    store.put(build_session())

    store.update_playlist_result(
        "session-1",
        PlaylistResult(
            playlist_id="playlist-1",
            url="https://open.spotify.com/playlist/playlist-1",
            requested_track_ids=("sunny",),
            tracks_added=("sunny",),
            snapshot_id="snapshot-1",
            idempotent_replay=False,
            partial_failures=(),
        ),
    )

    loaded = store.get("session-1")
    assert loaded is not None
    assert loaded.playlist_result is not None
    assert loaded.playlist_result.playlist_id == "playlist-1"
    assert loaded.playlist_result.requested_track_ids == ("sunny",)
    assert loaded.updated_at >= loaded.created_at


def build_session() -> RecommendationSession:
    return RecommendationSession(
        session_id="session-1",
        user_id="12175364859",
        prompt="cheer me up",
        intent={"label": "cheer-up"},
        recommended_track_ids=("sunny", "dance"),
        recommendations=(
            {
                "track": {"id": "sunny", "name": "Sunny Recovery"},
                "score": {"total": 0.9},
                "explanation": "bright",
            },
            {
                "track": {"id": "dance", "name": "Dance Again"},
                "score": {"total": 0.8},
                "explanation": "upbeat",
            },
        ),
        catalog_run_id="catalog-run",
        interaction_run_id="interaction-run",
        playlist_candidate={"track_ids": ["sunny", "dance"]},
        created_at="2026-07-04T00:00:00+00:00",
        updated_at="2026-07-04T00:00:00+00:00",
    )
