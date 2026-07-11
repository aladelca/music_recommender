from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from fastapi.testclient import TestClient

from music_recommender.api.app import create_app
from music_recommender.api.dependencies import require_approved_mutating_user
from music_recommender.auth.models import ProductUser
from music_recommender.product.playlist_export_service import PlaylistExportResult
from music_recommender.storage.protocols import PlaylistExportRecord

SESSION_ID = "40000000-0000-0000-0000-000000000001"
RECORDING = "30000000-0000-0000-0000-000000000001"


class FakePlaylistExportService:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def export(self, **kwargs: Any) -> PlaylistExportResult:
        self.calls.append(kwargs)
        replay = len(self.calls) > 1
        return PlaylistExportResult(
            record=replace(export_record(), status="complete", tracks_added=1),
            idempotent_replay=replay,
            resumed=False,
        )


def test_product_playlist_export_is_explicit_current_user_and_idempotent() -> None:
    client, service = build_client()
    payload = {
        "name": "Outside Finds",
        "description": "Reviewed discoveries",
        "public": True,
        "recording_mbids": [RECORDING],
    }
    headers = {"Idempotency-Key": "export-key-1"}

    created = client.post(
        f"/me/recommendations/{SESSION_ID}/playlist",
        json=payload,
        headers=headers,
    )
    replay = client.post(
        f"/me/recommendations/{SESSION_ID}/playlist",
        json=payload,
        headers=headers,
    )

    assert created.status_code == 201
    assert replay.status_code == 200
    assert created.json()["name"] == "Outside Finds"
    assert created.json()["public"] is True
    assert replay.json()["idempotent_replay"] is True
    assert service.calls[0] == {
        "account_id": "account-1",
        "session_id": SESSION_ID,
        "name": "Outside Finds",
        "description": "Reviewed discoveries",
        "public": True,
        "recording_mbids": (RECORDING,),
        "idempotency_key": "export-key-1",
    }


def test_product_playlist_export_requires_idempotency_header_and_visibility() -> None:
    client, service = build_client()

    response = client.post(
        f"/me/recommendations/{SESSION_ID}/playlist",
        json={
            "name": "Outside Finds",
            "recording_mbids": [RECORDING],
        },
    )

    assert response.status_code == 422
    assert service.calls == []


def build_client() -> tuple[TestClient, FakePlaylistExportService]:
    service = FakePlaylistExportService()
    app = create_app(load_env=False, playlist_export_service=service)
    user = ProductUser(
        account_id="account-1",
        display_name="Tester",
        access_status="approved",
        seed_ready=True,
        reauthorization_required=False,
    )
    app.dependency_overrides[require_approved_mutating_user] = lambda: user
    return TestClient(app), service


def export_record() -> PlaylistExportRecord:
    now = datetime(2030, 1, 1, tzinfo=UTC)
    return PlaylistExportRecord(
        id="50000000-0000-0000-0000-000000000001",
        session_id=SESSION_ID,
        account_id="account-1",
        spotify_playlist_id="playlist-1",
        spotify_playlist_url="https://open.spotify.com/playlist/playlist-1",
        name="Outside Finds",
        description="Reviewed discoveries",
        public=True,
        recording_mbids=(RECORDING,),
        spotify_track_ids=("spotify-1",),
        request_fingerprint="f" * 64,
        idempotency_key="export-key-1",
        status="creating",
        tracks_added=0,
        partial_failure=None,
        created_at=now,
        updated_at=now,
    )
