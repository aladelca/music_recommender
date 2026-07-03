from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

from music_recommender.models import JsonDict


class SpotifyPlaylistClient(Protocol):
    def create_playlist(
        self,
        user_id: str,
        *,
        name: str,
        description: str = "",
        public: bool = False,
    ) -> JsonDict: ...

    def add_playlist_items(self, playlist_id: str, track_ids_or_uris: list[str]) -> JsonDict: ...


@dataclass(frozen=True)
class PlaylistCreateResult:
    session_id: str
    playlist_id: str
    url: str | None
    tracks_added: tuple[str, ...]
    snapshot_id: str | None
    idempotent_replay: bool
    partial_failures: tuple[str, ...] = ()

    def to_dict(self) -> JsonDict:
        payload = asdict(self)
        payload["tracks_added"] = list(self.tracks_added)
        payload["partial_failures"] = list(self.partial_failures)
        return payload


@dataclass(frozen=True)
class PlaylistRecord:
    session_id: str
    playlist_id: str
    url: str | None
    track_ids: tuple[str, ...]
    snapshot_id: str | None

    def to_result(self, *, idempotent_replay: bool) -> PlaylistCreateResult:
        return PlaylistCreateResult(
            session_id=self.session_id,
            playlist_id=self.playlist_id,
            url=self.url,
            tracks_added=self.track_ids,
            snapshot_id=self.snapshot_id,
            idempotent_replay=idempotent_replay,
        )

    def to_dict(self) -> JsonDict:
        payload = asdict(self)
        payload["track_ids"] = list(self.track_ids)
        return payload


class JsonPlaylistRecordStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def get(self, session_id: str) -> PlaylistRecord | None:
        return self._load().get(session_id)

    def put(self, record: PlaylistRecord) -> None:
        records = self._load()
        records[record.session_id] = record
        self._write(records)

    def _load(self) -> dict[str, PlaylistRecord]:
        if not self.path.exists():
            return {}
        payload = json.loads(self.path.read_text())
        if not isinstance(payload, dict):
            raise ValueError(f"Playlist store must contain a JSON object: {self.path}")
        return {
            str(session_id): _playlist_record_from_payload(record)
            for session_id, record in payload.items()
            if isinstance(record, dict)
        }

    def _write(self, records: dict[str, PlaylistRecord]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(
                {session_id: record.to_dict() for session_id, record in records.items()},
                indent=2,
                sort_keys=True,
            )
        )


class PlaylistService:
    def __init__(
        self,
        *,
        spotify_client: SpotifyPlaylistClient,
        store: JsonPlaylistRecordStore,
        user_id: str,
    ) -> None:
        self.spotify_client = spotify_client
        self.store = store
        self.user_id = user_id

    def create_playlist(
        self,
        *,
        session_id: str,
        name: str,
        description: str,
        track_ids: tuple[str, ...],
        public: bool = False,
    ) -> PlaylistCreateResult:
        existing = self.store.get(session_id)
        if existing is not None:
            return existing.to_result(idempotent_replay=True)

        playlist = self.spotify_client.create_playlist(
            self.user_id,
            name=name,
            description=description,
            public=public,
        )
        playlist_id = str(playlist["id"])
        url = _playlist_url(playlist)
        try:
            add_result = self.spotify_client.add_playlist_items(playlist_id, list(track_ids))
        except Exception as exc:
            return PlaylistCreateResult(
                session_id=session_id,
                playlist_id=playlist_id,
                url=url,
                tracks_added=(),
                snapshot_id=None,
                idempotent_replay=False,
                partial_failures=(str(exc),),
            )
        record = PlaylistRecord(
            session_id=session_id,
            playlist_id=playlist_id,
            url=url,
            track_ids=track_ids,
            snapshot_id=_optional_str(add_result.get("snapshot_id")),
        )
        self.store.put(record)
        return record.to_result(idempotent_replay=False)


def _playlist_record_from_payload(payload: dict[str, Any]) -> PlaylistRecord:
    return PlaylistRecord(
        session_id=str(payload["session_id"]),
        playlist_id=str(payload["playlist_id"]),
        url=_optional_str(payload.get("url")),
        track_ids=tuple(str(track_id) for track_id in payload.get("track_ids", [])),
        snapshot_id=_optional_str(payload.get("snapshot_id")),
    )


def _playlist_url(payload: JsonDict) -> str | None:
    external_urls = payload.get("external_urls")
    if isinstance(external_urls, dict):
        return _optional_str(external_urls.get("spotify"))
    return None


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
