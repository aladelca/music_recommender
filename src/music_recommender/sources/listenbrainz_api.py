from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

import httpx

from music_recommender.models import JsonDict
from music_recommender.sources.http import ApiError, ApiHttpClient

LISTENBRAINZ_API_URL = "https://api.listenbrainz.org"
ListenBrainzSourceAdapter = Literal[
    "listenbrainz_artist_radio",
    "listenbrainz_tag_radio",
    "listenbrainz_labs_similarity",
]


class ListenBrainzUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class ListenBrainzCandidate:
    recording_mbid: str
    source_adapter: ListenBrainzSourceAdapter
    similar_artist_mbid: str | None
    similar_artist_name: str | None
    total_listen_count: int | None
    tags: tuple[str, ...]
    source_facts: dict[str, Any]

    def to_dict(self) -> JsonDict:
        return {
            "recording_mbid": self.recording_mbid,
            "source_adapter": self.source_adapter,
            "similar_artist_mbid": self.similar_artist_mbid,
            "similar_artist_name": self.similar_artist_name,
            "total_listen_count": self.total_listen_count,
            "tags": list(self.tags),
            "source_facts": dict(self.source_facts),
        }


@dataclass(frozen=True)
class ListenBrainzCandidateBatch:
    candidates: tuple[ListenBrainzCandidate, ...]
    retry_after_seconds: float | None


@dataclass(frozen=True)
class ListenBrainzRecordingMetadata:
    recording_mbid: str
    artist_credit: tuple[dict[str, Any], ...]
    tags: tuple[str, ...]
    release_data: dict[str, Any]
    name: str | None = None
    isrcs: tuple[str, ...] = ()


@dataclass(frozen=True)
class ListenBrainzMetadataBatch:
    records: tuple[ListenBrainzRecordingMetadata, ...]
    retry_after_seconds: float | None


class ListenBrainzApiClient:
    def __init__(
        self,
        *,
        contact_email: str,
        app_version: str,
        http: ApiHttpClient | None = None,
    ) -> None:
        normalized_email = contact_email.strip()
        if (
            "@" not in normalized_email
            or any(character.isspace() for character in normalized_email)
            or len(normalized_email) > 254
        ):
            raise ValueError("ListenBrainz contact email must be a valid contact address.")
        normalized_version = app_version.strip()
        if not normalized_version or any(character.isspace() for character in normalized_version):
            raise ValueError("ListenBrainz app version must not be empty or contain whitespace.")
        self.user_agent = f"OutsideTheLoop/{normalized_version} ({normalized_email})"
        self.http = http or ApiHttpClient(base_url=LISTENBRAINZ_API_URL)

    def close(self) -> None:
        self.http.close()

    def artist_radio(
        self,
        seed_artist_mbid: str,
        *,
        mode: Literal["easy", "medium", "hard"] = "medium",
        max_similar_artists: int = 10,
        max_recordings_per_artist: int = 5,
    ) -> ListenBrainzCandidateBatch:
        seed_mbid = _mbid(seed_artist_mbid)
        if mode not in {"easy", "medium", "hard"}:
            raise ValueError("ListenBrainz radio mode is invalid.")
        if not 1 <= max_similar_artists <= 20:
            raise ValueError("max_similar_artists must be between 1 and 20.")
        if not 1 <= max_recordings_per_artist <= 10:
            raise ValueError("max_recordings_per_artist must be between 1 and 10.")
        response = self._get(
            f"/1/lb-radio/artist/{seed_mbid}",
            params={
                "mode": mode,
                "max_similar_artists": max_similar_artists,
                "max_recordings_per_artist": max_recordings_per_artist,
                "pop_begin": 5,
                "pop_end": 80,
            },
        )
        candidates = _radio_candidates(
            response.json(),
            source_adapter="listenbrainz_artist_radio",
            tags=(),
            source_facts={"mode": mode},
        )
        return ListenBrainzCandidateBatch(
            candidates=candidates,
            retry_after_seconds=_retry_after_seconds(response),
        )

    def tag_radio(
        self,
        tags: tuple[str, ...],
        *,
        count: int = 25,
    ) -> ListenBrainzCandidateBatch:
        normalized_tags = _tags(tags)
        if not 1 <= count <= 50:
            raise ValueError("ListenBrainz tag count must be between 1 and 50.")
        response = self._get(
            "/1/lb-radio/tags",
            params={
                "tag": list(normalized_tags),
                "operator": "OR",
                "pop_begin": 5,
                "pop_end": 80,
                "count": count,
            },
        )
        candidates = _radio_candidates(
            response.json(),
            source_adapter="listenbrainz_tag_radio",
            tags=normalized_tags,
            source_facts={"operator": "OR"},
        )
        return ListenBrainzCandidateBatch(
            candidates=candidates,
            retry_after_seconds=_retry_after_seconds(response),
        )

    def recording_metadata(
        self,
        recording_mbids: tuple[str, ...],
    ) -> ListenBrainzMetadataBatch:
        normalized_mbids = tuple(dict.fromkeys(_mbid(mbid) for mbid in recording_mbids))
        if not 1 <= len(normalized_mbids) <= 100:
            raise ValueError("ListenBrainz metadata accepts between 1 and 100 recording MBIDs.")
        response = self._post(
            "/1/metadata/recording/",
            json={
                "recording_mbids": list(normalized_mbids),
                "inc": "artist tag release",
            },
        )
        payload = response.json()
        if not isinstance(payload, dict):
            raise ListenBrainzUnavailableError("ListenBrainz metadata is temporarily unavailable.")
        records: list[ListenBrainzRecordingMetadata] = []
        for recording_mbid in normalized_mbids:
            item = payload.get(recording_mbid)
            if not isinstance(item, dict):
                continue
            records.append(_recording_metadata(recording_mbid, item))
        return ListenBrainzMetadataBatch(
            records=tuple(records),
            retry_after_seconds=_retry_after_seconds(response),
        )

    def _get(self, path: str, **kwargs: Any) -> httpx.Response:
        try:
            return self.http.get(
                path,
                headers={"User-Agent": self.user_agent},
                **kwargs,
            )
        except (ApiError, ValueError):
            raise ListenBrainzUnavailableError("ListenBrainz is temporarily unavailable.") from None

    def _post(self, path: str, **kwargs: Any) -> httpx.Response:
        try:
            return self.http.post(
                path,
                headers={"User-Agent": self.user_agent},
                **kwargs,
            )
        except (ApiError, ValueError):
            raise ListenBrainzUnavailableError("ListenBrainz is temporarily unavailable.") from None


def _radio_candidates(
    payload: Any,
    *,
    source_adapter: ListenBrainzSourceAdapter,
    tags: tuple[str, ...],
    source_facts: dict[str, Any],
) -> tuple[ListenBrainzCandidate, ...]:
    candidates: list[ListenBrainzCandidate] = []
    seen: set[str] = set()
    for item in _recording_items(payload):
        try:
            recording_mbid = _mbid(item["recording_mbid"])
        except (KeyError, ValueError):
            continue
        if recording_mbid in seen:
            continue
        seen.add(recording_mbid)
        similar_artist_mbid = _optional_mbid(item.get("similar_artist_mbid"))
        similar_artist_name = _optional_text(item.get("similar_artist_name"))
        total_listen_count = _optional_nonnegative_int(item.get("total_listen_count"))
        candidate_facts = dict(source_facts)
        candidate_facts.update(_candidate_facts(item))
        candidates.append(
            ListenBrainzCandidate(
                recording_mbid=recording_mbid,
                source_adapter=source_adapter,
                similar_artist_mbid=similar_artist_mbid,
                similar_artist_name=similar_artist_name,
                total_listen_count=total_listen_count,
                tags=tags,
                source_facts=candidate_facts,
            )
        )
        if len(candidates) == 100:
            break
    return tuple(candidates)


def _recording_items(value: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if "recording_mbid" in value:
            items.append(value)
        else:
            for nested in value.values():
                items.extend(_recording_items(nested))
    elif isinstance(value, list):
        for nested in value:
            items.extend(_recording_items(nested))
    return items


def _recording_metadata(
    recording_mbid: str,
    payload: dict[str, Any],
) -> ListenBrainzRecordingMetadata:
    artist = payload.get("artist")
    artist_credit: list[dict[str, Any]] = []
    if isinstance(artist, dict) and isinstance(artist.get("artists"), list):
        for value in artist["artists"][:10]:
            if not isinstance(value, dict):
                continue
            mbid = _optional_mbid(value.get("artist_mbid"))
            name = _optional_text(value.get("name"))
            if mbid and name:
                artist_credit.append({"mbid": mbid, "name": name[:500]})
    tag_container = payload.get("tag")
    recording_tags: list[str] = []
    if isinstance(tag_container, dict) and isinstance(tag_container.get("recording"), list):
        for value in tag_container["recording"][:20]:
            if not isinstance(value, dict):
                continue
            tag = _optional_text(value.get("tag"))
            if tag and tag.casefold() not in {existing.casefold() for existing in recording_tags}:
                recording_tags.append(tag[:100])
            if len(recording_tags) == 10:
                break
    release = payload.get("release")
    release_data: dict[str, Any] = {}
    if isinstance(release, dict):
        for key in ("mbid", "name", "year"):
            value = release.get(key)
            if value is not None:
                release_data[key] = value
    recording = payload.get("recording")
    recording_name: str | None = None
    isrcs: list[str] = []
    if isinstance(recording, dict):
        recording_name = _optional_text(recording.get("name"))
        raw_isrcs = recording.get("isrcs")
        if isinstance(raw_isrcs, list):
            for value in raw_isrcs[:20]:
                normalized = str(value).strip().upper()
                if 5 <= len(normalized) <= 20 and normalized.isalnum() and normalized not in isrcs:
                    isrcs.append(normalized)
                if len(isrcs) == 10:
                    break
        first_release_date = _optional_text(recording.get("first_release_date"))
        if first_release_date:
            release_data["recording_first_release_date"] = first_release_date[:32]
        duration_ms = _optional_nonnegative_int(recording.get("length"))
        if duration_ms is not None:
            release_data["duration_ms"] = duration_ms
    return ListenBrainzRecordingMetadata(
        recording_mbid=recording_mbid,
        artist_credit=tuple(artist_credit),
        tags=tuple(recording_tags),
        release_data=release_data,
        name=recording_name[:500] if recording_name else None,
        isrcs=tuple(isrcs),
    )


def _candidate_facts(item: dict[str, Any]) -> dict[str, Any]:
    facts: dict[str, Any] = {}
    percent = item.get("percent")
    if (
        not isinstance(percent, bool)
        and isinstance(percent, (int, float))
        and math.isfinite(float(percent))
        and 0 <= float(percent) <= 100
    ):
        facts["percent"] = float(percent)
    tag_count = _optional_nonnegative_int(item.get("tag_count"))
    if tag_count is not None:
        facts["tag_count"] = tag_count
    source = _optional_text(item.get("source"))
    if source:
        facts["source"] = source[:100]
    return facts


def _retry_after_seconds(response: httpx.Response) -> float | None:
    remaining = response.headers.get("X-RateLimit-Remaining")
    if remaining is None:
        return None
    try:
        if int(remaining) > 0:
            return None
    except ValueError:
        return None
    for name in ("Retry-After", "X-RateLimit-Reset-In"):
        value = response.headers.get(name)
        if value is None:
            continue
        try:
            return max(float(value), 0.0)
        except ValueError:
            continue
    return None


def _tags(values: tuple[str, ...]) -> tuple[str, ...]:
    tags: list[str] = []
    for value in values:
        normalized = " ".join(value.split())
        if not 1 <= len(normalized) <= 64:
            raise ValueError("ListenBrainz tags must contain between 1 and 64 characters.")
        if normalized.casefold() not in {tag.casefold() for tag in tags}:
            tags.append(normalized)
    if not 1 <= len(tags) <= 3:
        raise ValueError("ListenBrainz tag radio accepts between one and three unique tags.")
    return tuple(tags)


def _mbid(value: Any) -> str:
    return str(UUID(str(value)))


def _optional_mbid(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return _mbid(value)
    except ValueError:
        return None


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _optional_nonnegative_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return None
    return normalized if normalized >= 0 else None
