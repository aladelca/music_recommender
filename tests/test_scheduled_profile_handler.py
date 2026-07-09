from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from music_recommender.api.models import ProfileSyncRequest
from music_recommender.api.scheduled_profile_handler import run_scheduled_profile_sync


class FakeProfileService:
    def __init__(self) -> None:
        self.request: ProfileSyncRequest | None = None

    def sync_profile(self, request: ProfileSyncRequest) -> dict[str, Any]:
        self.request = request
        return {
            "profile": {
                "user_id": "private-user",
                "liked_artist_names": ["Private Artist"],
            },
            "source_counts": {
                "saved_tracks": 12,
                "top_tracks": 30,
                "top_artists": 25,
                "playlists": 4,
                "playlist_tracks": 18,
                "recent_tracks": 7,
            },
            "synced_at": "2026-07-09T18:00:00+00:00",
            "missing_optional_scopes": [],
        }


def test_scheduled_profile_sync_uses_bounded_defaults_and_redacts_profile() -> None:
    service = FakeProfileService()

    result = run_scheduled_profile_sync(_scheduled_event(), service=service)

    assert service.request == ProfileSyncRequest(
        top_limit=20,
        saved_limit=20,
        top_time_ranges=["short_term", "medium_term", "long_term"],
        include_playlists=True,
        playlist_limit=10,
        playlist_track_limit=50,
        playlist_ids=[],
        include_recently_played=True,
        recently_played_limit=20,
        market=None,
    )
    assert result == {
        "status": "ok",
        "synced_at": "2026-07-09T18:00:00+00:00",
        "source_counts": {
            "saved_tracks": 12,
            "top_tracks": 30,
            "top_artists": 25,
            "playlists": 4,
            "playlist_tracks": 18,
            "recent_tracks": 7,
        },
        "missing_optional_scopes": [],
    }
    assert "profile" not in result
    assert "private-user" not in str(result)


@pytest.mark.parametrize(
    "event",
    [
        {},
        {"source": "aws.events", "detail-type": "Object Created"},
        {"source": "untrusted.source", "detail-type": "Scheduled Event"},
    ],
)
def test_scheduled_profile_sync_rejects_unrelated_events(event: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="EventBridge scheduled event"):
        run_scheduled_profile_sync(event, service=FakeProfileService())


def test_scheduled_profile_sync_propagates_service_failure() -> None:
    class FailingService:
        def sync_profile(self, request: ProfileSyncRequest) -> dict[str, Any]:
            raise RuntimeError("spotify unavailable")

    with pytest.raises(RuntimeError, match="spotify unavailable"):
        run_scheduled_profile_sync(_scheduled_event(), service=FailingService())


def test_scheduled_handler_does_not_import_the_full_api_service_graph() -> None:
    source = Path("src/music_recommender/api/scheduled_profile_handler.py").read_text()

    assert "music_recommender.api.services" not in source


def test_scheduled_handler_import_does_not_require_fastapi() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                "sys.modules['fastapi'] = None; "
                "sys.modules['yaml'] = None; "
                "import music_recommender.api.scheduled_profile_handler"
            ),
        ],
        cwd=Path.cwd(),
        env={**os.environ, "PYTHONPATH": str(Path("src").resolve())},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def _scheduled_event() -> dict[str, Any]:
    return {
        "version": "0",
        "id": "scheduled-event-id",
        "detail-type": "Scheduled Event",
        "source": "aws.events",
        "account": "571600852509",
        "time": "2026-07-09T18:00:00Z",
        "region": "us-east-1",
        "resources": ["arn:aws:events:us-east-1:571600852509:rule/profile-sync"],
        "detail": {},
    }
