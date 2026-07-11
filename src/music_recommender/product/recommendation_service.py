from __future__ import annotations

import base64
import binascii
import json
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from music_recommender.agents.intent import AdventureMode, PolicySafeIntentParser
from music_recommender.models import JsonDict
from music_recommender.product.spotify_mapping import (
    SourceCoverageReport,
    SpotifyMappingService,
    evaluate_source_coverage,
)
from music_recommender.recommender.evidence import (
    RecommendationEvidence,
    build_recommendation_evidence,
)
from music_recommender.recommender.models import (
    DiscoveryRankingPreferences,
    RankedDiscoveryCandidate,
)
from music_recommender.recommender.scoring import (
    DISCOVERY_RANKING_VERSION,
    rank_discovery_candidates,
)
from music_recommender.storage.protocols import (
    CandidateEdgeRepository,
    ExternalIdMappingRepository,
    MusicEntityRecord,
    RecommendationItemRecord,
    RecommendationRepository,
    RecommendationSessionBundle,
    RecommendationSessionRecord,
    UserPreferenceRepository,
    UserSeedRecord,
)


class RecommendationNotFoundError(LookupError):
    pass


class RecommendationSeedOwnershipError(ValueError):
    pass


class RecommendationSelectionError(ValueError):
    pass


class RecommendationCursorError(ValueError):
    pass


class RecommendationSeedReader(Protocol):
    def list_active(self, *, account_id: str) -> tuple[UserSeedRecord, ...]: ...


class RecommendationEntityRepository(Protocol):
    def get(self, *, mbid: str) -> MusicEntityRecord | None: ...

    def get_many(self, *, mbids: tuple[str, ...]) -> tuple[MusicEntityRecord, ...]: ...


class RecommendationSpotifyClient(Protocol):
    def search_tracks(
        self,
        query: str,
        *,
        limit: int = 5,
        market: str | None = None,
    ) -> tuple[JsonDict, ...]: ...

    def get_tracks(
        self,
        track_ids: tuple[str, ...],
        *,
        market: str | None = None,
    ) -> tuple[JsonDict, ...]: ...

    def close(self) -> None: ...


class RecommendationSpotifyClientFactory(Protocol):
    def create(self, *, account_id: str) -> RecommendationSpotifyClient: ...


@dataclass(frozen=True)
class RecommendationHistoryPage:
    sessions: tuple[RecommendationSessionRecord, ...]
    next_cursor: str | None


class RecommendationService:
    def __init__(
        self,
        *,
        seeds: RecommendationSeedReader,
        candidate_edges: CandidateEdgeRepository,
        entities: RecommendationEntityRepository,
        preferences: UserPreferenceRepository,
        mappings: ExternalIdMappingRepository,
        recommendations: RecommendationRepository,
        spotify_clients: RecommendationSpotifyClientFactory,
        market: str | None,
        intent_parser: PolicySafeIntentParser | None = None,
        now: Callable[[], datetime] | None = None,
        session_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.seeds = seeds
        self.candidate_edges = candidate_edges
        self.entities = entities
        self.preferences = preferences
        self.mappings = mappings
        self.recommendations = recommendations
        self.spotify_clients = spotify_clients
        self.market = market
        self.intent_parser = intent_parser or PolicySafeIntentParser()
        self.now = now or (lambda: datetime.now(UTC))
        self.session_id_factory = session_id_factory or (lambda: str(uuid.uuid4()))

    def generate(
        self,
        *,
        account_id: str,
        prompt: str,
        adventure: AdventureMode,
        allow_explicit: bool,
        seed_ids: tuple[str, ...],
    ) -> RecommendationSessionBundle:
        selected_seeds = self._owned_seeds(account_id=account_id, seed_ids=seed_ids)
        selected_seed_mbids = tuple(seed.mbid for seed in selected_seeds)
        intent = self.intent_parser.parse(
            prompt,
            adventure=adventure,
            allow_explicit=allow_explicit,
        )
        generated_at = _aware_utc(self.now())
        edges = self.candidate_edges.list_fresh(
            seed_mbids=selected_seed_mbids,
            now=generated_at,
        )
        candidate_mbids = tuple(dict.fromkeys(edge.candidate_recording_mbid for edge in edges))
        entity_records = self.entities.get_many(mbids=candidate_mbids)
        entities = {entity.mbid: entity for entity in entity_records}
        preference = self.preferences.get(account_id=account_id)
        ranking_preferences = DiscoveryRankingPreferences(
            blocked_artist_mbids=(
                preference.blocked_artist_mbids if preference is not None else ()
            ),
            blocked_recording_mbids=(
                preference.blocked_recording_mbids if preference is not None else ()
            ),
        )
        ranked = rank_discovery_candidates(
            edges,
            entities=entities,
            intent=intent,
            selected_seed_mbids=selected_seed_mbids,
            preferences=ranking_preferences,
            limit=50,
        )
        evidence_by_mbid = {
            candidate.entity.mbid: build_recommendation_evidence(candidate, intent=intent)
            for candidate in ranked
        }
        mapping_by_mbid: dict[str, str] = {}
        display_by_spotify_id: dict[str, JsonDict] = {}
        if ranked:
            spotify = self.spotify_clients.create(account_id=account_id)
            try:
                mapping_batch = SpotifyMappingService(
                    entities=self.entities,
                    mappings=self.mappings,
                    spotify=spotify,
                    market=self.market,
                    now=lambda: generated_at,
                ).map_ranked(recording_mbids=tuple(candidate.entity.mbid for candidate in ranked))
                mapping_by_mbid = {
                    mapping.recording_mbid: mapping.provider_id
                    for mapping in mapping_batch.mappings
                }
                spotify_ids = tuple(mapping.provider_id for mapping in mapping_batch.mappings)
                if spotify_ids:
                    display_by_spotify_id = {
                        str(display["spotify_track_id"]): display
                        for display in (
                            _spotify_display_snapshot(track)
                            for track in spotify.get_tracks(spotify_ids, market=self.market)
                        )
                        if display is not None
                    }
            finally:
                spotify.close()

        eligible_mapping_mbids = _eligible_mapping_mbids(
            ranked,
            mapping_by_mbid=mapping_by_mbid,
            display_by_spotify_id=display_by_spotify_id,
            allow_explicit=allow_explicit,
        )
        coverage = evaluate_source_coverage(
            ranked_recording_mbids=tuple(candidate.entity.mbid for candidate in ranked),
            mapped_recording_mbids=eligible_mapping_mbids,
            evidenced_recording_mbids=tuple(
                mbid for mbid, evidence in evidence_by_mbid.items() if evidence.verifiable
            ),
        )
        session_id = _uuid(self.session_id_factory(), "Recommendation session ID")
        candidate_by_mbid = {candidate.entity.mbid: candidate for candidate in ranked}
        rank_by_mbid = {
            candidate.entity.mbid: rank for rank, candidate in enumerate(ranked, start=1)
        }
        items = tuple(
            _recommendation_item(
                session_id=session_id,
                candidate=candidate_by_mbid[recording_mbid],
                evidence=evidence_by_mbid[recording_mbid],
                spotify_track_id=mapping_by_mbid[recording_mbid],
                display_snapshot=display_by_spotify_id[mapping_by_mbid[recording_mbid]],
                original_rank=rank_by_mbid[recording_mbid],
                created_at=generated_at,
            )
            for recording_mbid in coverage.returnable_recording_mbids
        )
        session = RecommendationSessionRecord(
            id=session_id,
            account_id=account_id,
            prompt=" ".join(prompt.split()),
            controls={
                "adventure": adventure,
                "allow_explicit": allow_explicit,
            },
            parsed_intent=intent.to_dict(),
            seed_ids=tuple(seed.id for seed in selected_seeds),
            source_snapshot=_source_snapshot(ranked, coverage),
            ranking_version=DISCOVERY_RANKING_VERSION,
            status=coverage.status,
            generated_at=generated_at,
            updated_at=generated_at,
            reviewed_playlist_name=None,
            reviewed_playlist_public=None,
        )
        return self.recommendations.create_with_items(session=session, items=items)

    def get(self, *, account_id: str, session_id: str) -> RecommendationSessionBundle:
        bundle = self.recommendations.get(
            account_id=account_id,
            session_id=_uuid(session_id, "Recommendation session ID"),
        )
        if bundle is None:
            raise RecommendationNotFoundError("Recommendation session was not found.")
        return bundle

    def history(
        self,
        *,
        account_id: str,
        limit: int,
        cursor: str | None,
    ) -> RecommendationHistoryPage:
        if not 1 <= limit <= 50:
            raise ValueError("History limit must be between 1 and 50.")
        before_generated_at, before_id = _decode_cursor(cursor) if cursor else (None, None)
        records = self.recommendations.list_sessions(
            account_id=account_id,
            limit=limit + 1,
            before_generated_at=before_generated_at,
            before_id=before_id,
        )
        page = records[:limit]
        next_cursor = (
            _encode_cursor(page[-1].generated_at, page[-1].id)
            if len(records) > limit and page
            else None
        )
        return RecommendationHistoryPage(sessions=page, next_cursor=next_cursor)

    def review(
        self,
        *,
        account_id: str,
        session_id: str,
        recording_mbids: tuple[str, ...],
        playlist_name: str,
        playlist_public: bool,
    ) -> RecommendationSessionBundle:
        normalized_session_id = _uuid(session_id, "Recommendation session ID")
        normalized_mbids = tuple(_uuid(mbid, "Reviewed recording MBID") for mbid in recording_mbids)
        if not 1 <= len(normalized_mbids) <= 10 or len(set(normalized_mbids)) != len(
            normalized_mbids
        ):
            raise RecommendationSelectionError(
                "Review between one and ten unique recommended recordings."
            )
        name = " ".join(playlist_name.split())
        if not 1 <= len(name) <= 100 or any(ord(character) < 32 for character in name):
            raise RecommendationSelectionError(
                "Playlist name must contain between one and 100 plain-text characters."
            )
        existing = self.get(account_id=account_id, session_id=normalized_session_id)
        owned_mbids = {item.recording_mbid for item in existing.items}
        if any(mbid not in owned_mbids for mbid in normalized_mbids):
            raise RecommendationSelectionError(
                "Reviewed recordings must belong to the recommendation session."
            )
        reviewed = self.recommendations.replace_selection(
            account_id=account_id,
            session_id=normalized_session_id,
            recording_mbids=normalized_mbids,
            playlist_name=name,
            playlist_public=playlist_public,
            reviewed_at=_aware_utc(self.now()),
        )
        if reviewed is None:
            raise RecommendationNotFoundError("Recommendation session was not found.")
        return reviewed

    def _owned_seeds(
        self,
        *,
        account_id: str,
        seed_ids: tuple[str, ...],
    ) -> tuple[UserSeedRecord, ...]:
        normalized_ids = tuple(_uuid(seed_id, "Seed ID") for seed_id in seed_ids)
        if not 1 <= len(normalized_ids) <= 5 or len(set(normalized_ids)) != len(normalized_ids):
            raise RecommendationSeedOwnershipError(
                "Select between one and five unique active seeds."
            )
        active = {seed.id: seed for seed in self.seeds.list_active(account_id=account_id)}
        if any(seed_id not in active for seed_id in normalized_ids):
            raise RecommendationSeedOwnershipError(
                "Selected seeds must belong to the current account."
            )
        return tuple(active[seed_id] for seed_id in normalized_ids)


def recommendation_bundle_payload(bundle: RecommendationSessionBundle) -> JsonDict:
    session = bundle.session
    return {
        "id": session.id,
        "status": session.status,
        "prompt": session.prompt,
        "controls": dict(session.controls),
        "intent": dict(session.parsed_intent),
        "seed_ids": list(session.seed_ids),
        "source_coverage": dict(session.source_snapshot.get("coverage", {})),
        "ranking_version": session.ranking_version,
        "generated_at": session.generated_at.isoformat(),
        "updated_at": session.updated_at.isoformat(),
        "review": {
            "playlist_name": session.reviewed_playlist_name,
            "public": session.reviewed_playlist_public,
        },
        "recommendations": [_item_payload(item) for item in bundle.items],
    }


def recommendation_history_payload(page: RecommendationHistoryPage) -> JsonDict:
    return {
        "sessions": [
            {
                "id": session.id,
                "status": session.status,
                "prompt": session.prompt,
                "ranking_version": session.ranking_version,
                "generated_at": session.generated_at.isoformat(),
            }
            for session in page.sessions
        ],
        "next_cursor": page.next_cursor,
    }


def _recommendation_item(
    *,
    session_id: str,
    candidate: RankedDiscoveryCandidate,
    evidence: RecommendationEvidence,
    spotify_track_id: str,
    display_snapshot: JsonDict,
    original_rank: int,
    created_at: datetime,
) -> RecommendationItemRecord:
    return RecommendationItemRecord(
        session_id=session_id,
        recording_mbid=candidate.entity.mbid,
        spotify_track_id=spotify_track_id,
        original_rank=original_rank,
        internal_score_components=asdict(candidate.score),
        evidence=evidence.to_dict(),
        display_snapshot=display_snapshot,
        selected=True,
        reviewed_order=None,
        created_at=created_at,
    )


def _item_payload(item: RecommendationItemRecord) -> JsonDict:
    return {
        "recording_mbid": item.recording_mbid,
        "original_rank": item.original_rank,
        "display": dict(item.display_snapshot),
        "evidence": dict(item.evidence),
        "selected": item.selected,
        "reviewed_order": item.reviewed_order,
    }


def _spotify_display_snapshot(track: JsonDict) -> JsonDict | None:
    track_id = _optional_text(track.get("id"), limit=255)
    name = _optional_text(track.get("name"), limit=500)
    artists = track.get("artists")
    explicit = track.get("explicit")
    if track_id is None or name is None or not isinstance(artists, list):
        return None
    artist_names = tuple(
        artist_name
        for artist_name in (
            _optional_text(artist.get("name"), limit=500)
            for artist in artists[:10]
            if isinstance(artist, dict)
        )
        if artist_name is not None
    )
    if not artist_names or not isinstance(explicit, bool):
        return None
    external_urls = track.get("external_urls")
    spotify_url = None
    if isinstance(external_urls, dict):
        spotify_url = _optional_text(external_urls.get("spotify"), limit=2_048)
    return {
        "spotify_track_id": track_id,
        "name": name,
        "artist_names": list(artist_names),
        "explicit": explicit,
        "spotify_url": spotify_url or f"https://open.spotify.com/track/{track_id}",
    }


def _mapping_is_eligible(
    recording_mbid: str,
    *,
    mapping_by_mbid: dict[str, str],
    display_by_spotify_id: dict[str, JsonDict],
    allow_explicit: bool,
) -> bool:
    spotify_id = mapping_by_mbid.get(recording_mbid)
    if spotify_id is None:
        return False
    display = display_by_spotify_id.get(spotify_id)
    if display is None:
        return False
    return allow_explicit or display.get("explicit") is False


def _eligible_mapping_mbids(
    ranked: list[RankedDiscoveryCandidate],
    *,
    mapping_by_mbid: dict[str, str],
    display_by_spotify_id: dict[str, JsonDict],
    allow_explicit: bool,
) -> tuple[str, ...]:
    eligible: list[str] = []
    seen_spotify_ids: set[str] = set()
    for candidate in ranked:
        recording_mbid = candidate.entity.mbid
        spotify_id = mapping_by_mbid.get(recording_mbid)
        if spotify_id is None or spotify_id in seen_spotify_ids:
            continue
        if not _mapping_is_eligible(
            recording_mbid,
            mapping_by_mbid=mapping_by_mbid,
            display_by_spotify_id=display_by_spotify_id,
            allow_explicit=allow_explicit,
        ):
            continue
        seen_spotify_ids.add(spotify_id)
        eligible.append(recording_mbid)
    return tuple(eligible)


def _source_snapshot(
    ranked: list[RankedDiscoveryCandidate],
    coverage: SourceCoverageReport,
) -> JsonDict:
    edges = [edge for candidate in ranked for edge in candidate.edges]
    return {
        "coverage": asdict(coverage),
        "source_adapters": sorted({edge.source_adapter for edge in edges}),
        "source_algorithm_versions": sorted({edge.algorithm_version for edge in edges}),
        "entity_source_versions": sorted(
            {
                candidate.entity.source_version
                for candidate in ranked
                if candidate.entity.source_version is not None
            }
        ),
        "oldest_source_fetch": (
            min(edge.fetched_at for edge in edges).isoformat() if edges else None
        ),
        "newest_source_fetch": (
            max(edge.fetched_at for edge in edges).isoformat() if edges else None
        ),
    }


def _encode_cursor(generated_at: datetime, session_id: str) -> str:
    payload = json.dumps(
        [generated_at.isoformat(), session_id],
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_cursor(value: str) -> tuple[datetime, str]:
    if not value or len(value) > 512:
        raise RecommendationCursorError("Recommendation history cursor is invalid.")
    try:
        padded = value + ("=" * (-len(value) % 4))
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        if not isinstance(payload, list) or len(payload) != 2:
            raise ValueError
        generated_at = datetime.fromisoformat(str(payload[0]))
        session_id = _uuid(str(payload[1]), "Recommendation history cursor")
    except (binascii.Error, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        raise RecommendationCursorError("Recommendation history cursor is invalid.") from None
    return _aware_utc(generated_at), session_id


def _uuid(value: str, name: str) -> str:
    try:
        return str(uuid.UUID(value))
    except ValueError:
        raise ValueError(f"{name} is invalid.") from None


def _optional_text(value: Any, *, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized or len(normalized) > limit or any(ord(char) < 32 for char in normalized):
        return None
    return normalized


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Recommendation timestamps must be timezone-aware.")
    return value.astimezone(UTC)
