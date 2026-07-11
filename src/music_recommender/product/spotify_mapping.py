from __future__ import annotations

import time
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Protocol
from uuid import UUID

from music_recommender.models import JsonDict
from music_recommender.storage.protocols import (
    ExternalIdMappingRecord,
    ExternalIdMappingRepository,
    MusicEntityRecord,
)

CoverageStatus = Literal["ready", "degraded", "insufficient"]
_MAPPING_TTL = timedelta(hours=24)
_MAX_RANKED_RECORDINGS = 50
_MAX_UNCACHED_CANDIDATES = 20
_MAX_SEARCH_REQUESTS = 20
_MAX_ELAPSED_SECONDS = 12.0


class SpotifyTrackSearch(Protocol):
    def search_tracks(
        self,
        query: str,
        *,
        limit: int = 5,
        market: str | None = None,
    ) -> tuple[JsonDict, ...]: ...


class MusicEntityReader(Protocol):
    def get(self, *, mbid: str) -> MusicEntityRecord | None: ...


@dataclass(frozen=True)
class SpotifyMappingBatch:
    mappings: tuple[ExternalIdMappingRecord, ...]
    unmapped_recording_mbids: tuple[str, ...]
    budget_exhausted: bool = False


@dataclass
class _SearchBudget:
    monotonic: Callable[[], float]
    started_at: float
    max_requests: int
    max_elapsed_seconds: float
    request_count: int = 0
    exhausted: bool = False

    def reserve(self) -> bool:
        if (
            self.request_count >= self.max_requests
            or self.monotonic() - self.started_at >= self.max_elapsed_seconds
        ):
            self.exhausted = True
            return False
        self.request_count += 1
        return True


@dataclass(frozen=True)
class SourceCoverageReport:
    status: CoverageStatus
    candidate_count: int
    mapped_count: int
    evidence_count: int
    duplicate_count: int
    evidence_coverage: float
    returnable_recording_mbids: tuple[str, ...]
    limitations: tuple[str, ...]


class SpotifyMappingService:
    def __init__(
        self,
        *,
        entities: MusicEntityReader,
        mappings: ExternalIdMappingRepository,
        spotify: SpotifyTrackSearch,
        market: str | None,
        now: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        max_uncached_candidates: int = _MAX_UNCACHED_CANDIDATES,
        max_search_requests: int = _MAX_SEARCH_REQUESTS,
        max_elapsed_seconds: float = _MAX_ELAPSED_SECONDS,
    ) -> None:
        if not 1 <= max_uncached_candidates <= _MAX_RANKED_RECORDINGS:
            raise ValueError("Spotify mapping candidate budget must be between one and 50.")
        if not 1 <= max_search_requests <= 100:
            raise ValueError("Spotify mapping search budget must be between one and 100.")
        if max_elapsed_seconds <= 0 or max_elapsed_seconds > 20:
            raise ValueError(
                "Spotify mapping time budget must be greater than zero and at most 20."
            )
        self.entities = entities
        self.mappings = mappings
        self.spotify = spotify
        self.market = market
        self.now = now or (lambda: datetime.now(UTC))
        self.monotonic = monotonic
        self.max_uncached_candidates = max_uncached_candidates
        self.max_search_requests = max_search_requests
        self.max_elapsed_seconds = max_elapsed_seconds

    def map_ranked(self, *, recording_mbids: tuple[str, ...]) -> SpotifyMappingBatch:
        normalized_mbids = _unique_mbids(recording_mbids, limit=_MAX_RANKED_RECORDINGS)
        now = _aware_utc(self.now())
        budget = _SearchBudget(
            monotonic=self.monotonic,
            started_at=self.monotonic(),
            max_requests=self.max_search_requests,
            max_elapsed_seconds=self.max_elapsed_seconds,
        )
        mapped: list[ExternalIdMappingRecord] = []
        unmapped: list[str] = []
        uncached_candidates = 0
        candidate_budget_exhausted = False
        for recording_mbid in normalized_mbids:
            cached = self.mappings.get_fresh(
                recording_mbid=recording_mbid,
                provider="spotify",
                now=now,
            )
            if cached is not None:
                mapped.append(cached)
                continue
            entity = self.entities.get(mbid=recording_mbid)
            if entity is None or entity.entity_type != "recording" or entity.expires_at <= now:
                unmapped.append(recording_mbid)
                continue
            if uncached_candidates >= self.max_uncached_candidates:
                candidate_budget_exhausted = True
                unmapped.append(recording_mbid)
                continue
            uncached_candidates += 1
            match = self._find_match(
                name=entity.name,
                artist_names=tuple(
                    str(credit["name"])
                    for credit in entity.artist_credit
                    if isinstance(credit.get("name"), str)
                ),
                isrcs=entity.isrcs,
                budget=budget,
            )
            if match is None:
                unmapped.append(recording_mbid)
                continue
            provider_id, mapping_source, confidence = match
            record = self.mappings.upsert(
                ExternalIdMappingRecord(
                    recording_mbid=recording_mbid,
                    provider="spotify",
                    provider_id=provider_id,
                    mapping_source=mapping_source,
                    confidence=confidence,
                    fetched_at=now,
                    expires_at=now + _MAPPING_TTL,
                )
            )
            mapped.append(record)
        return SpotifyMappingBatch(
            mappings=tuple(mapped),
            unmapped_recording_mbids=tuple(unmapped),
            budget_exhausted=candidate_budget_exhausted or budget.exhausted,
        )

    def _find_match(
        self,
        *,
        name: str,
        artist_names: tuple[str, ...],
        isrcs: tuple[str, ...],
        budget: _SearchBudget,
    ) -> tuple[str, str, float] | None:
        for isrc in isrcs[:3]:
            normalized_isrc = _normalized_isrc(isrc)
            if normalized_isrc is None:
                continue
            if not budget.reserve():
                return None
            tracks = self.spotify.search_tracks(
                f"isrc:{normalized_isrc}",
                limit=5,
                market=self.market,
            )
            for track in tracks:
                if _track_isrc(track) == normalized_isrc:
                    track_id = _track_id(track)
                    if track_id is not None:
                        return track_id, "isrc_exact", 1.0

        if not artist_names:
            return None
        if not budget.reserve():
            return None
        query = f'track:"{_query_text(name)}" artist:"{_query_text(artist_names[0])}"'
        tracks = self.spotify.search_tracks(query, limit=5, market=self.market)
        expected_name = _match_text(name)
        expected_artists = {_match_text(artist) for artist in artist_names}
        for track in tracks:
            if _match_text(_track_name(track)) != expected_name:
                continue
            candidate_artists = {_match_text(artist) for artist in _track_artists(track)}
            if not expected_artists.intersection(candidate_artists):
                continue
            track_id = _track_id(track)
            if track_id is not None:
                return track_id, "name_artist_exact", 0.9
        return None


def evaluate_source_coverage(
    *,
    ranked_recording_mbids: tuple[str, ...],
    mapped_recording_mbids: tuple[str, ...],
    evidenced_recording_mbids: tuple[str, ...],
    required_track_count: int = 10,
) -> SourceCoverageReport:
    if not 1 <= required_track_count <= 50:
        raise ValueError("required_track_count must be between 1 and 50.")
    ranked = _unique_mbids(ranked_recording_mbids, limit=_MAX_RANKED_RECORDINGS)
    duplicate_count = len(ranked_recording_mbids) - len(ranked)
    mapped = set(_unique_mbids(mapped_recording_mbids, limit=_MAX_RANKED_RECORDINGS))
    evidenced = set(_unique_mbids(evidenced_recording_mbids, limit=_MAX_RANKED_RECORDINGS))
    returnable = tuple(mbid for mbid in ranked if mbid in mapped)[:required_track_count]
    evidence_count = sum(mbid in evidenced for mbid in returnable)
    evidence_coverage = evidence_count / len(returnable) if returnable else 0.0
    limitations: tuple[str, ...]
    status: CoverageStatus
    if len(returnable) < required_track_count:
        status = "insufficient"
        limitations = (f"fewer_than_{required_track_count}_spotify_mappings",)
    elif evidence_coverage < 0.9:
        status = "degraded"
        limitations = ("evidence_coverage_below_90_percent",)
    else:
        status = "ready"
        limitations = ()
    return SourceCoverageReport(
        status=status,
        candidate_count=len(ranked),
        mapped_count=len(returnable),
        evidence_count=evidence_count,
        duplicate_count=duplicate_count,
        evidence_coverage=round(evidence_coverage, 4),
        returnable_recording_mbids=returnable,
        limitations=limitations,
    )


def _unique_mbids(values: tuple[str, ...], *, limit: int) -> tuple[str, ...]:
    unique: list[str] = []
    for value in values:
        try:
            mbid = str(UUID(value))
        except ValueError:
            raise ValueError("Recording MBIDs must be valid UUIDs.") from None
        if mbid not in unique:
            unique.append(mbid)
        if len(unique) == limit:
            break
    return tuple(unique)


def _track_id(track: JsonDict) -> str | None:
    value = track.get("id")
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized or len(normalized) > 255 or any(ord(char) < 32 for char in normalized):
        return None
    return normalized


def _track_name(track: JsonDict) -> str:
    value = track.get("name")
    return value if isinstance(value, str) else ""


def _track_artists(track: JsonDict) -> tuple[str, ...]:
    values = track.get("artists")
    if not isinstance(values, list):
        return ()
    return tuple(
        str(value["name"])
        for value in values[:10]
        if isinstance(value, dict) and isinstance(value.get("name"), str)
    )


def _track_isrc(track: JsonDict) -> str | None:
    external_ids = track.get("external_ids")
    if not isinstance(external_ids, dict):
        return None
    return _normalized_isrc(external_ids.get("isrc"))


def _normalized_isrc(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = "".join(character for character in value.upper() if character.isalnum())
    return normalized if 5 <= len(normalized) <= 20 else None


def _query_text(value: str) -> str:
    return " ".join(value.replace("\\", " ").replace('"', " ").split())[:100]


def _match_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(normalized.split())


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Spotify mapping timestamps must be timezone-aware.")
    return value.astimezone(UTC)
