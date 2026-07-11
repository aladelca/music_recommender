from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from music_recommender.product.playlist_export_service import (
    PlaylistExportConflictError,
    PlaylistExportReviewRequiredError,
    PlaylistExportService,
    PlaylistExportUnavailableError,
)
from music_recommender.sources.spotify_user import SpotifyServiceUnavailable
from music_recommender.storage.protocols import (
    PlaylistExportRecord,
    PlaylistExportReservation,
    RecommendationItemRecord,
    RecommendationSessionBundle,
    RecommendationSessionRecord,
)

SESSION_ID = "40000000-0000-0000-0000-000000000001"
EXPORT_ID = "50000000-0000-0000-0000-000000000001"
RECORDING_ONE = "30000000-0000-0000-0000-000000000001"
RECORDING_TWO = "30000000-0000-0000-0000-000000000002"


class FakeRecommendations:
    def __init__(self, bundle: RecommendationSessionBundle) -> None:
        self.bundle = bundle

    def get(self, *, account_id: str, session_id: str) -> RecommendationSessionBundle | None:
        if account_id == self.bundle.session.account_id and session_id == self.bundle.session.id:
            return self.bundle
        return None


class InMemoryExports:
    def __init__(self, *, claim_first_reservation: bool = True) -> None:
        self.record: PlaylistExportRecord | None = None
        self.claim_first_reservation = claim_first_reservation

    def create_or_get(self, record: PlaylistExportRecord) -> PlaylistExportReservation:
        if self.record is None:
            self.record = record
            return PlaylistExportReservation(
                record=self.record,
                created=self.claim_first_reservation,
            )
        return PlaylistExportReservation(record=self.record, created=False)

    def set_playlist_created(self, **kwargs: Any) -> PlaylistExportRecord:
        assert self.record is not None
        self.record = replace(
            self.record,
            spotify_playlist_id=kwargs["spotify_playlist_id"],
            spotify_playlist_url=kwargs["spotify_playlist_url"],
            status="adding_items",
            updated_at=kwargs["updated_at"],
        )
        return self.record

    def mark_complete(self, **kwargs: Any) -> PlaylistExportRecord:
        assert self.record is not None
        self.record = replace(
            self.record,
            status="complete",
            tracks_added=kwargs["tracks_added"],
            partial_failure=None,
            updated_at=kwargs["updated_at"],
        )
        return self.record

    def mark_partial_failure(self, **kwargs: Any) -> PlaylistExportRecord:
        assert self.record is not None
        self.record = replace(
            self.record,
            status="partial_failure",
            partial_failure={"code": kwargs["error_code"]},
            updated_at=kwargs["updated_at"],
        )
        return self.record


class FakeSpotify:
    def __init__(
        self,
        *,
        fail_replace_once: bool = False,
        fail_create_once: bool = False,
        invalid_create_response: bool = False,
    ) -> None:
        self.fail_replace_once = fail_replace_once
        self.fail_create_once = fail_create_once
        self.invalid_create_response = invalid_create_response
        self.create_calls: list[dict[str, Any]] = []
        self.replace_calls: list[tuple[str, list[str]]] = []
        self.close_count = 0

    def create_playlist(self, **kwargs: Any) -> dict[str, Any]:
        self.create_calls.append(kwargs)
        if self.fail_create_once:
            self.fail_create_once = False
            raise SpotifyServiceUnavailable("Spotify unavailable.", status_code=500)
        if self.invalid_create_response:
            return {}
        return {
            "id": "playlist-1",
            "external_urls": {"spotify": "https://open.spotify.com/playlist/playlist-1"},
        }

    def replace_playlist_items(
        self,
        playlist_id: str,
        track_ids_or_uris: list[str],
    ) -> dict[str, str]:
        self.replace_calls.append((playlist_id, track_ids_or_uris))
        if self.fail_replace_once:
            self.fail_replace_once = False
            raise SpotifyServiceUnavailable("Spotify unavailable.", status_code=500)
        return {"snapshot_id": "snapshot-1"}

    def close(self) -> None:
        self.close_count += 1


class FakeSpotifyFactory:
    def __init__(self, spotify: FakeSpotify) -> None:
        self.spotify = spotify
        self.accounts: list[str] = []

    def create(self, *, account_id: str) -> FakeSpotify:
        self.accounts.append(account_id)
        return self.spotify


def test_playlist_export_is_reviewed_current_user_public_and_idempotent() -> None:
    service, exports, spotify, factory = build_service()

    first = export(service)
    replay = export(service)

    assert first.record.status == "complete"
    assert first.record.spotify_playlist_id == "playlist-1"
    assert first.record.tracks_added == 2
    assert first.idempotent_replay is False
    assert replay.idempotent_replay is True
    assert spotify.create_calls == [
        {
            "name": "Outside Finds",
            "description": "Reviewed discoveries",
            "public": True,
        }
    ]
    assert spotify.replace_calls == [("playlist-1", ["spotify-2", "spotify-1"])]
    assert factory.accounts == ["account-1"]
    assert exports.record is not None
    assert exports.record.recording_mbids == (RECORDING_TWO, RECORDING_ONE)


def test_playlist_export_same_idempotency_key_with_different_payload_conflicts() -> None:
    service, _, spotify, _ = build_service()
    export(service)

    with pytest.raises(PlaylistExportConflictError):
        export(service, description="Different payload")

    assert len(spotify.create_calls) == 1


def test_playlist_export_persists_playlist_before_safe_replace_retry() -> None:
    service, exports, spotify, _ = build_service(fail_replace_once=True)

    with pytest.raises(SpotifyServiceUnavailable):
        export(service)

    assert exports.record is not None
    assert exports.record.status == "partial_failure"
    assert exports.record.spotify_playlist_id == "playlist-1"
    resumed = export(service)

    assert resumed.record.status == "complete"
    assert resumed.resumed is True
    assert len(spotify.create_calls) == 1
    assert len(spotify.replace_calls) == 2


def test_playlist_export_does_not_duplicate_uncertain_playlist_creation() -> None:
    service, exports, spotify, _ = build_service(fail_create_once=True)

    with pytest.raises(SpotifyServiceUnavailable):
        export(service)
    with pytest.raises(PlaylistExportUnavailableError, match="manual reconciliation"):
        export(service)

    assert exports.record is not None
    assert exports.record.spotify_playlist_id is None
    assert len(spotify.create_calls) == 1


def test_playlist_export_does_not_run_spotify_for_an_existing_active_reservation() -> None:
    service, exports, spotify, factory = build_service(claim_first_reservation=False)

    with pytest.raises(PlaylistExportConflictError, match="already in progress"):
        export(service)

    assert exports.record is not None
    assert exports.record.status == "creating"
    assert spotify.create_calls == []
    assert factory.accounts == []


def test_playlist_export_records_an_invalid_spotify_creation_response_as_uncertain() -> None:
    service, exports, spotify, _ = build_service(invalid_create_response=True)

    with pytest.raises(PlaylistExportUnavailableError, match="invalid playlist response"):
        export(service)
    with pytest.raises(PlaylistExportUnavailableError, match="manual reconciliation"):
        export(service)

    assert exports.record is not None
    assert exports.record.status == "partial_failure"
    assert exports.record.partial_failure == {"code": "spotify_invalid_response"}
    assert len(spotify.create_calls) == 1


def test_playlist_export_requires_exact_reviewed_order_and_name() -> None:
    service, _, spotify, factory = build_service()

    with pytest.raises(PlaylistExportReviewRequiredError):
        service.export(
            account_id="account-1",
            session_id=SESSION_ID,
            name="Outside Finds",
            description="Reviewed discoveries",
            public=True,
            recording_mbids=(RECORDING_ONE, RECORDING_TWO),
            idempotency_key="export-key-1",
        )

    assert spotify.create_calls == []
    assert factory.accounts == []


def export(
    service: PlaylistExportService,
    *,
    description: str = "Reviewed discoveries",
) -> Any:
    return service.export(
        account_id="account-1",
        session_id=SESSION_ID,
        name="Outside Finds",
        description=description,
        public=True,
        recording_mbids=(RECORDING_TWO, RECORDING_ONE),
        idempotency_key="export-key-1",
    )


def build_service(
    *,
    fail_replace_once: bool = False,
    fail_create_once: bool = False,
    invalid_create_response: bool = False,
    claim_first_reservation: bool = True,
) -> tuple[PlaylistExportService, InMemoryExports, FakeSpotify, FakeSpotifyFactory]:
    now = datetime(2030, 1, 1, tzinfo=UTC)
    exports = InMemoryExports(claim_first_reservation=claim_first_reservation)
    spotify = FakeSpotify(
        fail_replace_once=fail_replace_once,
        fail_create_once=fail_create_once,
        invalid_create_response=invalid_create_response,
    )
    factory = FakeSpotifyFactory(spotify)
    return (
        PlaylistExportService(
            recommendations=FakeRecommendations(reviewed_bundle(now)),
            exports=exports,
            spotify_clients=factory,
            now=lambda: now,
            export_id_factory=lambda: EXPORT_ID,
        ),
        exports,
        spotify,
        factory,
    )


def reviewed_bundle(now: datetime) -> RecommendationSessionBundle:
    session = RecommendationSessionRecord(
        id=SESSION_ID,
        account_id="account-1",
        prompt="Outside my loop",
        controls={"adventure": "adventurous", "allow_explicit": True},
        parsed_intent={"label": "seed-led", "tags": []},
        seed_ids=("00000000-0000-0000-0000-000000000001",),
        source_snapshot={"coverage": {"status": "ready"}},
        ranking_version="explicit-discovery-v1",
        status="reviewed",
        generated_at=now,
        updated_at=now,
        reviewed_playlist_name="Outside Finds",
        reviewed_playlist_public=True,
    )
    items = (
        item(now, RECORDING_ONE, "spotify-1", original_rank=1, reviewed_order=2),
        item(now, RECORDING_TWO, "spotify-2", original_rank=2, reviewed_order=1),
    )
    return RecommendationSessionBundle(session=session, items=items)


def item(
    now: datetime,
    recording_mbid: str,
    spotify_track_id: str,
    *,
    original_rank: int,
    reviewed_order: int,
) -> RecommendationItemRecord:
    return RecommendationItemRecord(
        session_id=SESSION_ID,
        recording_mbid=recording_mbid,
        spotify_track_id=spotify_track_id,
        original_rank=original_rank,
        internal_score_components={},
        evidence={},
        display_snapshot={},
        selected=True,
        reviewed_order=reviewed_order,
        created_at=now,
    )
