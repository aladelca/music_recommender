from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from music_recommender.product.recommendation_service import (
    RecommendationCursorError,
    RecommendationNotFoundError,
    RecommendationSeedOwnershipError,
    RecommendationService,
    recommendation_bundle_payload,
)
from music_recommender.storage.protocols import (
    CandidateEdgeRecord,
    ExternalIdMappingRecord,
    MusicEntityRecord,
    RecommendationItemRecord,
    RecommendationSessionBundle,
    RecommendationSessionRecord,
    UserSeedRecord,
)

SEED_ID = "00000000-0000-0000-0000-000000000001"
SEED_MBID = "10000000-0000-0000-0000-000000000001"


class InMemorySeeds:
    def __init__(self, seed: UserSeedRecord) -> None:
        self.seed = seed

    def list_active(self, *, account_id: str) -> tuple[UserSeedRecord, ...]:
        return (self.seed,) if account_id == self.seed.account_id else ()


class InMemoryEdges:
    def __init__(self, records: tuple[CandidateEdgeRecord, ...]) -> None:
        self.records = records

    def list_fresh(self, **kwargs: Any) -> tuple[CandidateEdgeRecord, ...]:
        return tuple(
            edge
            for edge in self.records
            if edge.seed_mbid in kwargs["seed_mbids"] and edge.expires_at > kwargs["now"]
        )

    def upsert(self, edge: CandidateEdgeRecord) -> CandidateEdgeRecord:
        raise AssertionError(f"Unexpected edge write: {edge}")


class InMemoryEntities:
    def __init__(self, records: tuple[MusicEntityRecord, ...]) -> None:
        self.records = {record.mbid: record for record in records}

    def get(self, *, mbid: str) -> MusicEntityRecord | None:
        return self.records.get(mbid)

    def get_many(self, *, mbids: tuple[str, ...]) -> tuple[MusicEntityRecord, ...]:
        return tuple(self.records[mbid] for mbid in mbids if mbid in self.records)


class EmptyPreferences:
    def get(self, *, account_id: str) -> None:
        assert account_id == "account-1"
        return None


class InMemoryMappings:
    def __init__(self) -> None:
        self.records: dict[str, ExternalIdMappingRecord] = {}

    def get_fresh(self, **kwargs: Any) -> ExternalIdMappingRecord | None:
        record = self.records.get(kwargs["recording_mbid"])
        return record if record and record.expires_at > kwargs["now"] else None

    def upsert(self, record: ExternalIdMappingRecord) -> ExternalIdMappingRecord:
        self.records[record.recording_mbid] = record
        return record


class InMemoryRecommendations:
    def __init__(self) -> None:
        self.records: dict[str, RecommendationSessionBundle] = {}

    def create_with_items(
        self,
        *,
        session: RecommendationSessionRecord,
        items: tuple[RecommendationItemRecord, ...],
    ) -> RecommendationSessionBundle:
        bundle = RecommendationSessionBundle(session=session, items=items)
        self.records[session.id] = bundle
        return bundle

    def get(self, *, account_id: str, session_id: str) -> RecommendationSessionBundle | None:
        bundle = self.records.get(session_id)
        return bundle if bundle and bundle.session.account_id == account_id else None

    def list_sessions(self, **kwargs: Any) -> tuple[RecommendationSessionRecord, ...]:
        records = sorted(
            (
                bundle.session
                for bundle in self.records.values()
                if bundle.session.account_id == kwargs["account_id"]
            ),
            key=lambda session: (session.generated_at, session.id),
            reverse=True,
        )
        if kwargs["before_generated_at"] is not None:
            boundary = (kwargs["before_generated_at"], kwargs["before_id"])
            records = [
                session for session in records if (session.generated_at, session.id) < boundary
            ]
        return tuple(records[: kwargs["limit"]])

    def replace_selection(self, **kwargs: Any) -> RecommendationSessionBundle | None:
        bundle = self.get(account_id=kwargs["account_id"], session_id=kwargs["session_id"])
        if bundle is None:
            return None
        order = {mbid: index for index, mbid in enumerate(kwargs["recording_mbids"], start=1)}
        reviewed = RecommendationSessionBundle(
            session=replace(
                bundle.session,
                status="reviewed",
                updated_at=kwargs["reviewed_at"],
                reviewed_playlist_name=kwargs["playlist_name"],
                reviewed_playlist_public=kwargs["playlist_public"],
            ),
            items=tuple(
                replace(
                    item,
                    selected=item.recording_mbid in order,
                    reviewed_order=order.get(item.recording_mbid),
                )
                for item in bundle.items
            ),
        )
        self.records[bundle.session.id] = reviewed
        return reviewed


class FakeSpotify:
    def __init__(self) -> None:
        self.closed = False
        self.search_queries: list[str] = []

    def search_tracks(self, query: str, **kwargs: Any) -> tuple[dict[str, Any], ...]:
        self.search_queries.append(query)
        isrc = query.removeprefix("isrc:")
        index = int(isrc[-2:])
        spotify_id = "spotify-10" if index == 11 else f"spotify-{index}"
        return (
            {
                "id": spotify_id,
                "name": f"Track {index}",
                "artists": [{"name": f"Artist {index}"}],
                "external_ids": {"isrc": isrc},
            },
        )

    def get_tracks(
        self,
        track_ids: tuple[str, ...],
        **kwargs: Any,
    ) -> tuple[dict[str, Any], ...]:
        return tuple(
            {
                "id": track_id,
                "name": f"Track {track_id.split('-')[-1]}",
                "artists": [{"name": f"Artist {track_id.split('-')[-1]}"}],
                "explicit": track_id == "spotify-12",
                "external_urls": {"spotify": f"https://open.spotify.com/track/{track_id}"},
            }
            for track_id in track_ids
        )

    def close(self) -> None:
        self.closed = True


class FakeSpotifyFactory:
    def __init__(self, spotify: FakeSpotify) -> None:
        self.spotify = spotify
        self.accounts: list[str] = []

    def create(self, *, account_id: str) -> FakeSpotify:
        self.accounts.append(account_id)
        self.spotify.closed = False
        return self.spotify


def test_recommendation_service_generates_account_scoped_evidenced_session() -> None:
    service, repositories, spotify = build_service()

    bundle = service.generate(
        account_id="account-1",
        prompt="Late night trip hop",
        adventure="balanced",
        allow_explicit=False,
        seed_ids=(SEED_ID,),
    )
    payload = recommendation_bundle_payload(bundle)

    assert bundle.session.status == "ready"
    assert len(bundle.items) == 10
    assert all(item.display_snapshot["explicit"] is False for item in bundle.items)
    assert len({item.spotify_track_id for item in bundle.items}) == 10
    assert all(item.evidence["verifiable"] is True for item in bundle.items)
    assert payload["source_coverage"]["evidence_coverage"] == 1.0
    assert payload["ranking_version"] == "explicit-discovery-v1"
    assert "internal_score_components" not in str(payload)
    assert spotify.closed is True
    assert len(spotify.search_queries) == 12
    assert (
        repositories.get(
            account_id="account-2",
            session_id=bundle.session.id,
        )
        is None
    )


def test_recommendation_service_requires_owned_seed_ids_before_spotify_calls() -> None:
    service, _, spotify = build_service()

    with pytest.raises(RecommendationSeedOwnershipError, match="current account"):
        service.generate(
            account_id="account-1",
            prompt="Late night trip hop",
            adventure="balanced",
            allow_explicit=True,
            seed_ids=("00000000-0000-0000-0000-000000000099",),
        )

    assert spotify.search_queries == []


def test_recommendation_review_and_history_are_owned_ordered_and_cursor_paginated() -> None:
    service, _, _ = build_service()
    first = service.generate(
        account_id="account-1",
        prompt="First session jazz",
        adventure="familiar",
        allow_explicit=True,
        seed_ids=(SEED_ID,),
    )
    second = service.generate(
        account_id="account-1",
        prompt="Second session ambient",
        adventure="adventurous",
        allow_explicit=True,
        seed_ids=(SEED_ID,),
    )
    selected = tuple(item.recording_mbid for item in reversed(second.items[:2]))

    reviewed = service.review(
        account_id="account-1",
        session_id=second.session.id,
        recording_mbids=selected,
        playlist_name="Late Night Finds",
        playlist_public=True,
    )
    first_page = service.history(account_id="account-1", limit=1, cursor=None)
    second_page = service.history(
        account_id="account-1",
        limit=1,
        cursor=first_page.next_cursor,
    )

    assert reviewed.session.status == "reviewed"
    assert reviewed.session.reviewed_playlist_name == "Late Night Finds"
    assert [
        item.recording_mbid
        for item in sorted(
            (item for item in reviewed.items if item.selected),
            key=lambda item: item.reviewed_order or 0,
        )
    ] == list(selected)
    assert first_page.sessions[0].id == second.session.id
    assert second_page.sessions[0].id == first.session.id
    with pytest.raises(RecommendationNotFoundError):
        service.get(account_id="account-2", session_id=second.session.id)
    with pytest.raises(RecommendationCursorError):
        service.history(account_id="account-1", limit=10, cursor="not-base64!")


def build_service() -> tuple[RecommendationService, InMemoryRecommendations, FakeSpotify]:
    now = datetime(2030, 1, 1, tzinfo=UTC)
    seed = UserSeedRecord(
        id=SEED_ID,
        account_id="account-1",
        entity_type="artist",
        mbid=SEED_MBID,
        display_name="Portishead",
        position=1,
        selected_at=now,
    )
    entities = tuple(recording(index, now) for index in range(1, 13))
    edges = tuple(candidate_edge(index, now) for index in range(1, 13))
    recommendations = InMemoryRecommendations()
    spotify = FakeSpotify()
    session_ids = iter(
        (
            "40000000-0000-0000-0000-000000000001",
            "40000000-0000-0000-0000-000000000002",
            "40000000-0000-0000-0000-000000000003",
        )
    )
    return (
        RecommendationService(
            seeds=InMemorySeeds(seed),
            candidate_edges=InMemoryEdges(edges),
            entities=InMemoryEntities(entities),
            preferences=EmptyPreferences(),
            mappings=InMemoryMappings(),
            recommendations=recommendations,
            spotify_clients=FakeSpotifyFactory(spotify),
            market="CA",
            now=lambda: now,
            session_id_factory=lambda: next(session_ids),
        ),
        recommendations,
        spotify,
    )


def recording(index: int, now: datetime) -> MusicEntityRecord:
    return MusicEntityRecord(
        mbid=f"30000000-0000-0000-0000-{index:012d}",
        entity_type="recording",
        name=f"Track {index}",
        artist_credit=(
            {
                "mbid": f"20000000-0000-0000-0000-{index:012d}",
                "name": f"Artist {index}",
            },
        ),
        release_data={"tags": ["trip hop", "downtempo"]},
        isrcs=(f"TESTISRC0000{index:02d}",),
        source="listenbrainz",
        source_version="lb-core-v1",
        fetched_at=now,
        expires_at=now + timedelta(days=30),
    )


def candidate_edge(index: int, now: datetime) -> CandidateEdgeRecord:
    return CandidateEdgeRecord(
        seed_mbid=SEED_MBID,
        candidate_recording_mbid=f"30000000-0000-0000-0000-{index:012d}",
        source_adapter="listenbrainz_artist_radio",
        algorithm_version="lb-core-v1",
        strength=0.7,
        listener_count=100 + index,
        source_facts={
            "similar_artist_mbid": f"20000000-0000-0000-0000-{index:012d}",
            "tags": ["trip hop"],
        },
        fetched_at=now,
        expires_at=now + timedelta(days=7),
    )
