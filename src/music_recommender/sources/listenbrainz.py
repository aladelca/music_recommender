from __future__ import annotations

import hashlib
import json
import logging
import tarfile
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any, TextIO

from music_recommender.models import JsonDict, ListenBrainzListenRecord

LOGGER = logging.getLogger(__name__)


class ListenBrainzDumpReader:
    def iter_listens(
        self,
        path: Path,
        *,
        run_id: str,
        user_hash_salt: str = "",
        limit: int | None = None,
    ) -> Iterator[ListenBrainzListenRecord]:
        emitted = 0
        for line in iter_dump_lines(path):
            if limit is not None and emitted >= limit:
                return
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                LOGGER.warning("Skipping invalid ListenBrainz JSON line")
                continue
            record = listen_record_from_payload(
                payload,
                run_id=run_id,
                user_hash_salt=user_hash_salt,
            )
            if record is None:
                continue
            emitted += 1
            yield record


def iter_dump_lines(path: Path) -> Iterator[str]:
    if path.is_dir():
        for child in sorted(path.iterdir()):
            yield from iter_dump_lines(child)
        return

    if path.name.endswith(".tar.zst"):
        yield from _iter_tar_zst_lines(path)
        return

    if path.suffix == ".zst":
        yield from _iter_zst_text_lines(path)
        return

    with path.open(encoding="utf-8") as file:
        yield from _iter_text_lines(file)


def listen_record_from_payload(
    payload: Any,
    *,
    run_id: str,
    user_hash_salt: str,
) -> ListenBrainzListenRecord | None:
    if not isinstance(payload, dict):
        return None
    metadata = _dict(payload.get("track_metadata"))
    additional_info = _dict(metadata.get("additional_info"))
    user_name = _optional_str(payload.get("user_name") or payload.get("user_id"))
    artist_name = _optional_str(metadata.get("artist_name"))
    track_name = _optional_str(metadata.get("track_name"))
    if user_name is None or (artist_name is None and track_name is None):
        return None

    return ListenBrainzListenRecord(
        user_id_hash=hash_user_id(user_name, user_hash_salt),
        listened_at=_optional_int(payload.get("listened_at")),
        recording_mbid=_optional_str(
            additional_info.get("recording_mbid")
            or metadata.get("recording_mbid")
            or payload.get("recording_mbid")
        ),
        artist_name=artist_name,
        track_name=track_name,
        release_name=_optional_str(metadata.get("release_name")),
        isrc=_first_isrc(additional_info.get("isrc") or metadata.get("isrc")),
        spotify_track_id=spotify_track_id_from_value(
            additional_info.get("spotify_id")
            or additional_info.get("spotify_uri")
            or metadata.get("spotify_id")
        ),
        source="listenbrainz",
        source_run_id=run_id,
    )


def hash_user_id(user_name: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{user_name}".encode()).hexdigest()


def spotify_track_id_from_value(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    for marker in ("spotify:track:", "open.spotify.com/track/"):
        if marker in text:
            return text.split(marker, 1)[1].split("?", 1)[0].split("/", 1)[0]
    if len(text) == 22 and text.isalnum():
        return text
    return None


def _iter_tar_zst_lines(path: Path) -> Iterator[str]:
    try:
        import zstandard as zstd
    except ImportError as error:
        raise RuntimeError("zstandard is required to read ListenBrainz .tar.zst dumps") from error

    with path.open("rb") as compressed:
        reader = zstd.ZstdDecompressor().stream_reader(compressed)
        with tarfile.open(fileobj=reader, mode="r|") as archive:
            for member in archive:
                if not member.isfile() or not member.name.endswith(".listens"):
                    continue
                extracted = archive.extractfile(member)
                if extracted is None:
                    continue
                for raw_line in extracted:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if line:
                        yield line


def _iter_zst_text_lines(path: Path) -> Iterator[str]:
    try:
        import zstandard as zstd
    except ImportError as error:
        raise RuntimeError("zstandard is required to read ListenBrainz .zst dumps") from error

    with path.open("rb") as compressed:
        reader = zstd.ZstdDecompressor().stream_reader(compressed)
        for raw_line in reader:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if line:
                yield line


def _iter_text_lines(file: TextIO) -> Iterator[str]:
    for line in file:
        stripped = line.strip()
        if stripped:
            yield stripped


def _dict(value: Any) -> JsonDict:
    return value if isinstance(value, dict) else {}


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _first_isrc(value: Any) -> str | None:
    if isinstance(value, list):
        for item in value:
            if item:
                return str(item)
        return None
    return _optional_str(value)


def records_to_dicts(records: Iterable[ListenBrainzListenRecord]) -> list[JsonDict]:
    return [record.to_dict() for record in records]
