from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from typing import Any

from music_recommender.models import AudioFeaturesRecord, JsonDict
from music_recommender.sources.http import ApiError, ApiHttpClient

API_BASE_URL = "https://api.reccobeats.com/v1"
LOGGER = logging.getLogger(__name__)
SPOTIFY_TRACK_URL_RE = re.compile(r"open\.spotify\.com/track/([^/?]+)")


class ReccoBeatsClient:
    def __init__(
        self,
        *,
        http: ApiHttpClient | None = None,
        chunk_size: int = 40,
    ) -> None:
        self.http = http or ApiHttpClient(base_url=API_BASE_URL)
        self.chunk_size = chunk_size

    def close(self) -> None:
        self.http.close()

    def get_audio_features(
        self,
        track_ids: Iterable[str],
        fetched_at: str,
    ) -> list[AudioFeaturesRecord]:
        unique_track_ids = list(dict.fromkeys(track_ids))
        records: list[AudioFeaturesRecord] = []
        for chunk in _chunks(unique_track_ids, self.chunk_size):
            records.extend(self._get_audio_features_chunk(chunk, fetched_at))
        return records

    def _get_audio_features_chunk(
        self,
        track_ids: list[str],
        fetched_at: str,
    ) -> list[AudioFeaturesRecord]:
        try:
            response = self.http.get(
                "/audio-features",
                params={"ids": ",".join(track_ids)},
                expected_statuses=(200,),
            )
        except ApiError as error:
            if error.status_code in {403, 404}:
                LOGGER.warning("ReccoBeats audio features unavailable: %s", error)
                return [
                    AudioFeaturesRecord(
                        spotify_track_id=track_id,
                        enabled=True,
                        status="unavailable",
                        source="reccobeats",
                        error_code=error.status_code,
                        fetched_at=fetched_at,
                    )
                    for track_id in track_ids
                ]
            raise

        payload = response.json()
        rows = _content_rows(payload)
        by_track_id = {
            spotify_track_id: row
            for row in rows
            if (spotify_track_id := _spotify_track_id_from_row(row)) is not None
        }
        records = []
        for track_id in track_ids:
            row = by_track_id.get(track_id)
            if row is None:
                records.append(
                    AudioFeaturesRecord(
                        spotify_track_id=track_id,
                        enabled=True,
                        status="miss",
                        source="reccobeats",
                        fetched_at=fetched_at,
                    )
                )
                continue
            records.append(
                AudioFeaturesRecord(
                    spotify_track_id=track_id,
                    enabled=True,
                    status="hit",
                    source="reccobeats",
                    isrc=_optional_str(row.get("isrc")),
                    raw=dict(row),
                    fetched_at=fetched_at,
                )
            )
        return records


def _chunks(values: list[str], size: int) -> Iterable[list[str]]:
    if size < 1:
        raise ValueError("chunk_size must be at least 1")
    for index in range(0, len(values), size):
        yield values[index : index + size]


def _content_rows(payload: Any) -> list[JsonDict]:
    if isinstance(payload, dict):
        content = payload.get("content")
        if isinstance(content, list):
            return [row for row in content if isinstance(row, dict)]
        if isinstance(payload.get("audio_features"), list):
            return [row for row in payload["audio_features"] if isinstance(row, dict)]
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    return []


def _spotify_track_id_from_row(row: JsonDict) -> str | None:
    row_id = row.get("spotify_track_id")
    if row_id:
        return str(row_id)
    href = row.get("href")
    if not href:
        return None
    match = SPOTIFY_TRACK_URL_RE.search(str(href))
    if match is None:
        return None
    return match.group(1)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
