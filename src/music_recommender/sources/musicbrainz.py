from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID

from music_recommender.models import JsonDict
from music_recommender.sources.http import ApiError, ApiHttpClient
from music_recommender.storage.protocols import MusicEntityType

MUSICBRAINZ_BASE_URL = "https://musicbrainz.org/ws/2"


class MusicBrainzUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class MusicBrainzSearchResult:
    mbid: str
    entity_type: MusicEntityType
    name: str
    artist_credit: tuple[dict[str, Any], ...]
    release_data: dict[str, Any]
    isrcs: tuple[str, ...]

    def to_dict(self) -> JsonDict:
        return {
            "mbid": self.mbid,
            "entity_type": self.entity_type,
            "name": self.name,
            "artist_credit": [dict(credit) for credit in self.artist_credit],
            "release_data": dict(self.release_data),
            "isrcs": list(self.isrcs),
            "source": "musicbrainz",
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> MusicBrainzSearchResult:
        entity_type = str(payload["entity_type"])
        if entity_type not in {"artist", "recording"}:
            raise ValueError("Unsupported MusicBrainz entity type.")
        return cls(
            mbid=_mbid(payload["mbid"]),
            entity_type=cast(MusicEntityType, entity_type),
            name=_required_name(payload["name"]),
            artist_credit=tuple(
                dict(credit)
                for credit in payload.get("artist_credit", [])
                if isinstance(credit, dict)
            ),
            release_data=(
                dict(payload.get("release_data", {}))
                if isinstance(payload.get("release_data", {}), dict)
                else {}
            ),
            isrcs=tuple(str(isrc) for isrc in payload.get("isrcs", []) if isrc),
        )


class MusicBrainzClient:
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
            raise ValueError("MusicBrainz contact email must be a valid contact address.")
        normalized_version = app_version.strip()
        if not normalized_version or any(character.isspace() for character in normalized_version):
            raise ValueError("MusicBrainz app version must not be empty or contain whitespace.")
        self.user_agent = f"OutsideTheLoop/{normalized_version} ({normalized_email})"
        self.http = http or ApiHttpClient(base_url=MUSICBRAINZ_BASE_URL)

    def close(self) -> None:
        self.http.close()

    def search(
        self,
        query: str,
        *,
        entity_type: MusicEntityType,
        limit: int = 10,
    ) -> tuple[MusicBrainzSearchResult, ...]:
        normalized_query = _search_text(query)
        if entity_type not in {"artist", "recording"}:
            raise ValueError("entity_type must be artist or recording.")
        if not 1 <= limit <= 10:
            raise ValueError("MusicBrainz search limit must be between 1 and 10.")
        escaped = normalized_query.replace("\\", "\\\\").replace('"', '\\"')
        field = "artist" if entity_type == "artist" else "recording"
        try:
            response = self.http.get(
                f"/{field}",
                headers={"User-Agent": self.user_agent},
                params={
                    "query": f'{field}:"{escaped}"',
                    "fmt": "json",
                    "limit": limit,
                },
            )
            payload = response.json()
        except (ApiError, ValueError):
            raise MusicBrainzUnavailableError(
                "MusicBrainz search is temporarily unavailable."
            ) from None
        if not isinstance(payload, dict):
            raise MusicBrainzUnavailableError("MusicBrainz search is temporarily unavailable.")
        key = "artists" if entity_type == "artist" else "recordings"
        items = payload.get(key, [])
        if not isinstance(items, list):
            raise MusicBrainzUnavailableError("MusicBrainz search is temporarily unavailable.")
        results: list[MusicBrainzSearchResult] = []
        for item in items[:limit]:
            if not isinstance(item, dict):
                continue
            try:
                result = (
                    _artist_result(item) if entity_type == "artist" else _recording_result(item)
                )
            except (KeyError, TypeError, ValueError):
                continue
            results.append(result)
        return tuple(results)


def _artist_result(payload: dict[str, Any]) -> MusicBrainzSearchResult:
    release_data: dict[str, Any] = {}
    country = _optional_text(payload.get("country"))
    disambiguation = _optional_text(payload.get("disambiguation"))
    tags = _tag_names(payload.get("tags"))
    if country:
        release_data["country"] = country
    if disambiguation:
        release_data["disambiguation"] = disambiguation
    if tags:
        release_data["tags"] = tags
    return MusicBrainzSearchResult(
        mbid=_mbid(payload["id"]),
        entity_type="artist",
        name=_required_name(payload["name"]),
        artist_credit=(),
        release_data=release_data,
        isrcs=(),
    )


def _recording_result(payload: dict[str, Any]) -> MusicBrainzSearchResult:
    release_data: dict[str, Any] = {}
    first_release_date = _optional_text(payload.get("first-release-date"))
    if first_release_date:
        release_data["first_release_date"] = first_release_date
    releases = _releases(payload.get("releases"))
    if releases:
        release_data["releases"] = releases
    tags = _tag_names(payload.get("tags"))
    if tags:
        release_data["tags"] = tags
    return MusicBrainzSearchResult(
        mbid=_mbid(payload["id"]),
        entity_type="recording",
        name=_required_name(payload["title"]),
        artist_credit=_artist_credit(payload.get("artist-credit")),
        release_data=release_data,
        isrcs=tuple(str(isrc) for isrc in payload.get("isrcs", [])[:10] if isrc),
    )


def _artist_credit(value: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, list):
        return ()
    credits: list[dict[str, Any]] = []
    for entry in value[:10]:
        if not isinstance(entry, dict):
            continue
        artist = entry.get("artist")
        if not isinstance(artist, dict):
            continue
        name = _optional_text(entry.get("name") or artist.get("name"))
        mbid_value = artist.get("id")
        if name is None or mbid_value is None:
            continue
        try:
            artist_mbid = _mbid(mbid_value)
        except ValueError:
            continue
        credits.append({"mbid": artist_mbid, "name": name})
    return tuple(credits)


def _releases(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    releases: list[dict[str, Any]] = []
    for release in value[:3]:
        if not isinstance(release, dict):
            continue
        try:
            normalized: dict[str, Any] = {
                "mbid": _mbid(release["id"]),
                "title": _required_name(release["title"]),
            }
        except (KeyError, ValueError):
            continue
        for source_key, target_key in (("date", "date"), ("country", "country")):
            text = _optional_text(release.get(source_key))
            if text:
                normalized[target_key] = text
        releases.append(normalized)
    return releases


def _tag_names(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    names: list[str] = []
    for tag in value[:20]:
        if not isinstance(tag, dict):
            continue
        name = _optional_text(tag.get("name"))
        if name and name.casefold() not in {existing.casefold() for existing in names}:
            names.append(name[:100])
        if len(names) == 10:
            break
    return names


def _search_text(value: str) -> str:
    normalized = " ".join(value.split())
    if not 2 <= len(normalized) <= 100 or any(ord(character) < 32 for character in normalized):
        raise ValueError("MusicBrainz query must contain between 2 and 100 plain-text characters.")
    return normalized


def _mbid(value: Any) -> str:
    return str(UUID(str(value)))


def _required_name(value: Any) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError("MusicBrainz name must not be empty.")
    return normalized[:500]


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None
