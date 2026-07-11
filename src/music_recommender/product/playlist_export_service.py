from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from music_recommender.models import JsonDict
from music_recommender.sources.spotify_user import SpotifyClientError
from music_recommender.storage.protocols import (
    PlaylistExportRecord,
    PlaylistExportRepository,
    RecommendationSessionBundle,
)


class PlaylistExportNotFoundError(LookupError):
    pass


class PlaylistExportReviewRequiredError(ValueError):
    pass


class PlaylistExportConflictError(RuntimeError):
    pass


class PlaylistExportUnavailableError(RuntimeError):
    pass


class PlaylistSpotifyClient(Protocol):
    def create_playlist(
        self,
        *,
        name: str,
        description: str = "",
        public: bool = False,
    ) -> JsonDict: ...

    def replace_playlist_items(
        self,
        playlist_id: str,
        track_ids_or_uris: list[str],
    ) -> JsonDict: ...

    def close(self) -> None: ...


class PlaylistSpotifyClientFactory(Protocol):
    def create(self, *, account_id: str) -> PlaylistSpotifyClient: ...


class PlaylistRecommendationReader(Protocol):
    def get(
        self,
        *,
        account_id: str,
        session_id: str,
    ) -> RecommendationSessionBundle | None: ...


@dataclass(frozen=True)
class PlaylistExportResult:
    record: PlaylistExportRecord
    idempotent_replay: bool
    resumed: bool

    def to_dict(self) -> JsonDict:
        return {
            "id": self.record.id,
            "session_id": self.record.session_id,
            "status": self.record.status,
            "spotify_playlist_id": self.record.spotify_playlist_id,
            "spotify_playlist_url": self.record.spotify_playlist_url,
            "name": self.record.name,
            "public": self.record.public,
            "tracks_added": self.record.tracks_added,
            "track_count": len(self.record.spotify_track_ids),
            "idempotent_replay": self.idempotent_replay,
            "resumed": self.resumed,
        }


class PlaylistExportService:
    def __init__(
        self,
        *,
        recommendations: PlaylistRecommendationReader,
        exports: PlaylistExportRepository,
        spotify_clients: PlaylistSpotifyClientFactory,
        now: Callable[[], datetime] | None = None,
        export_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.recommendations = recommendations
        self.exports = exports
        self.spotify_clients = spotify_clients
        self.now = now or (lambda: datetime.now(UTC))
        self.export_id_factory = export_id_factory or (lambda: str(uuid.uuid4()))

    def export(
        self,
        *,
        account_id: str,
        session_id: str,
        name: str,
        description: str,
        public: bool,
        recording_mbids: tuple[str, ...],
        idempotency_key: str,
    ) -> PlaylistExportResult:
        normalized_session_id = _uuid(session_id, "Recommendation session ID")
        normalized_name = _plain_text(name, name="Playlist name", minimum=1, maximum=100)
        normalized_description = _plain_text(
            description,
            name="Playlist description",
            minimum=0,
            maximum=300,
        )
        normalized_key = _plain_text(
            idempotency_key,
            name="Idempotency-Key",
            minimum=1,
            maximum=255,
        )
        normalized_mbids = tuple(_uuid(mbid, "Reviewed recording MBID") for mbid in recording_mbids)
        if not 1 <= len(normalized_mbids) <= 20 or len(set(normalized_mbids)) != len(
            normalized_mbids
        ):
            raise PlaylistExportReviewRequiredError(
                "Export between one and 20 unique reviewed recordings."
            )
        bundle = self.recommendations.get(
            account_id=account_id,
            session_id=normalized_session_id,
        )
        if bundle is None:
            raise PlaylistExportNotFoundError("Recommendation session was not found.")
        selected_items = tuple(
            sorted(
                (
                    item
                    for item in bundle.items
                    if item.selected and item.reviewed_order is not None
                ),
                key=lambda item: item.reviewed_order or 0,
            )
        )
        selected_mbids = tuple(item.recording_mbid for item in selected_items)
        if (
            bundle.session.status != "reviewed"
            or selected_mbids != normalized_mbids
            or bundle.session.reviewed_playlist_name != normalized_name
            or bundle.session.reviewed_playlist_public != public
        ):
            raise PlaylistExportReviewRequiredError(
                "Playlist name, visibility, and ordered tracks must match the reviewed session."
            )
        spotify_track_ids = tuple(
            item.spotify_track_id for item in selected_items if item.spotify_track_id is not None
        )
        if len(spotify_track_ids) != len(selected_items):
            raise PlaylistExportReviewRequiredError(
                "Every reviewed recording must have a Spotify export mapping."
            )
        fingerprint = _request_fingerprint(
            session_id=normalized_session_id,
            name=normalized_name,
            description=normalized_description,
            public=public,
            recording_mbids=normalized_mbids,
            spotify_track_ids=spotify_track_ids,
        )
        created_at = _aware_utc(self.now())
        reservation = self.exports.create_or_get(
            PlaylistExportRecord(
                id=_uuid(self.export_id_factory(), "Playlist export ID"),
                session_id=normalized_session_id,
                account_id=account_id,
                spotify_playlist_id=None,
                spotify_playlist_url=None,
                name=normalized_name,
                description=normalized_description,
                public=public,
                recording_mbids=normalized_mbids,
                spotify_track_ids=spotify_track_ids,
                request_fingerprint=fingerprint,
                idempotency_key=normalized_key,
                status="creating",
                tracks_added=0,
                partial_failure=None,
                created_at=created_at,
                updated_at=created_at,
            )
        )
        reserved = reservation.record
        if (
            reserved.request_fingerprint != fingerprint
            or reserved.idempotency_key != normalized_key
            or reserved.session_id != normalized_session_id
        ):
            raise PlaylistExportConflictError(
                "Idempotency key or recommendation session already has a different export."
            )
        if reserved.status == "complete":
            return PlaylistExportResult(
                record=reserved,
                idempotent_replay=True,
                resumed=False,
            )
        if (
            not reservation.created
            and reserved.status == "creating"
            and reserved.spotify_playlist_id is None
        ):
            raise PlaylistExportConflictError("Playlist export is already in progress.")
        if (
            reserved.status == "partial_failure"
            and reserved.spotify_playlist_id is None
            and reserved.partial_failure is not None
            and reserved.partial_failure.get("code")
            in {
                "spotify_invalid_response",
                "spotify_service_unavailable",
                "spotify_transport_failure",
            }
        ):
            raise PlaylistExportUnavailableError(
                "Playlist creation outcome is uncertain and requires manual reconciliation."
            )

        resumed = reserved.spotify_playlist_id is not None
        spotify = self.spotify_clients.create(account_id=account_id)
        try:
            working = reserved
            if working.spotify_playlist_id is None:
                try:
                    playlist = spotify.create_playlist(
                        name=working.name,
                        description=working.description,
                        public=working.public,
                    )
                except SpotifyClientError as error:
                    self.exports.mark_partial_failure(
                        account_id=account_id,
                        export_id=working.id,
                        error_code=_spotify_error_code(error),
                        updated_at=_aware_utc(self.now()),
                    )
                    raise
                try:
                    playlist_id, playlist_url = _playlist_identity(playlist)
                except PlaylistExportUnavailableError:
                    self.exports.mark_partial_failure(
                        account_id=account_id,
                        export_id=working.id,
                        error_code="spotify_invalid_response",
                        updated_at=_aware_utc(self.now()),
                    )
                    raise
                working = self.exports.set_playlist_created(
                    account_id=account_id,
                    export_id=working.id,
                    spotify_playlist_id=playlist_id,
                    spotify_playlist_url=playlist_url,
                    updated_at=_aware_utc(self.now()),
                )
            try:
                spotify.replace_playlist_items(
                    working.spotify_playlist_id or "",
                    list(working.spotify_track_ids),
                )
            except SpotifyClientError as error:
                self.exports.mark_partial_failure(
                    account_id=account_id,
                    export_id=working.id,
                    error_code=_spotify_error_code(error),
                    updated_at=_aware_utc(self.now()),
                )
                raise
            completed = self.exports.mark_complete(
                account_id=account_id,
                export_id=working.id,
                tracks_added=len(working.spotify_track_ids),
                updated_at=_aware_utc(self.now()),
            )
        finally:
            spotify.close()
        return PlaylistExportResult(
            record=completed,
            idempotent_replay=False,
            resumed=resumed,
        )


def _request_fingerprint(
    *,
    session_id: str,
    name: str,
    description: str,
    public: bool,
    recording_mbids: tuple[str, ...],
    spotify_track_ids: tuple[str, ...],
) -> str:
    payload = {
        "session_id": session_id,
        "name": name,
        "description": description,
        "public": public,
        "recording_mbids": list(recording_mbids),
        "spotify_track_ids": list(spotify_track_ids),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _playlist_identity(payload: JsonDict) -> tuple[str, str | None]:
    playlist_id = payload.get("id")
    if not isinstance(playlist_id, str) or not playlist_id.strip():
        raise PlaylistExportUnavailableError("Spotify returned an invalid playlist response.")
    external_urls = payload.get("external_urls")
    playlist_url = None
    if isinstance(external_urls, dict) and isinstance(external_urls.get("spotify"), str):
        playlist_url = str(external_urls["spotify"])
    return playlist_id.strip(), playlist_url


def _spotify_error_code(error: SpotifyClientError) -> str:
    status_code = error.status_code
    if status_code == 429:
        return "spotify_rate_limited"
    if status_code is not None and 500 <= status_code <= 599:
        return "spotify_service_unavailable"
    if status_code == 401:
        return "spotify_reauthorization_required"
    if status_code == 403:
        return "spotify_permission_denied"
    if status_code == 0:
        return "spotify_transport_failure"
    return "spotify_export_failed"


def _plain_text(value: str, *, name: str, minimum: int, maximum: int) -> str:
    normalized = " ".join(value.split())
    if not minimum <= len(normalized) <= maximum or any(
        ord(character) < 32 for character in normalized
    ):
        raise ValueError(f"{name} must contain between {minimum} and {maximum} characters.")
    return normalized


def _uuid(value: str, name: str) -> str:
    try:
        return str(uuid.UUID(value))
    except ValueError:
        raise ValueError(f"{name} is invalid.") from None


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Playlist export timestamps must be timezone-aware.")
    return value.astimezone(UTC)
