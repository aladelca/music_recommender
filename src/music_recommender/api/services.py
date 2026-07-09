from __future__ import annotations

import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from music_recommender.agents.intent import parse_intent_with_agent
from music_recommender.agents.orchestrator import AgenticRecommendationService
from music_recommender.api.errors import ApiConfigurationError, ApiNotFoundError, ApiValidationError
from music_recommender.api.models import (
    FeedbackRequest,
    PlaylistCreateRequest,
    ProfileSyncRequest,
    RecommendationRequest,
)
from music_recommender.config import Settings, load_settings
from music_recommender.models import JsonDict
from music_recommender.recommender.catalog import load_recommender_catalog_from_run
from music_recommender.recommender.feedback import FeedbackService, JsonFeedbackStore
from music_recommender.recommender.models import CatalogTrack, RecommenderCatalog, UserTasteProfile
from music_recommender.recommender.playlists import JsonPlaylistRecordStore, PlaylistService
from music_recommender.recommender.profile import (
    JsonProfileCache,
    ProfileCache,
    ProfileSnapshot,
    SpotifyProfileSyncService,
)
from music_recommender.recommender.sessions import (
    JsonRecommendationSessionStore,
    PlaylistResult,
    RecommendationSession,
    RecommendationSessionStore,
)
from music_recommender.sources.spotify_user import SpotifyUserClient
from music_recommender.storage.dynamodb import (
    DynamoDBFeedbackStore,
    DynamoDBPlaylistRecordStore,
    DynamoDBProfileCache,
    DynamoDBRecommendationSessionStore,
)


class DemoApiService:
    def __init__(
        self,
        *,
        settings_loader: Callable[[], Settings] = load_settings,
        dynamodb_client_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.settings_loader = settings_loader
        self.dynamodb_client_factory = dynamodb_client_factory

    def recommend(self, request: RecommendationRequest) -> JsonDict:
        settings = self._settings()
        catalog_run_id = request.catalog_run_id or os.getenv("RECOMMENDER_CATALOG_RUN_ID")
        if not catalog_run_id:
            raise ApiConfigurationError(
                "Set RECOMMENDER_CATALOG_RUN_ID or pass catalog_run_id in the request."
            )
        interaction_run_id = (
            request.interaction_run_id or os.getenv("RECOMMENDER_INTERACTION_RUN_ID") or None
        )
        catalog = load_recommender_catalog_from_run(
            settings.recommender_data_root,
            catalog_run_id=catalog_run_id,
            interaction_run_id=interaction_run_id,
            data_mode=settings.recommender_data_mode,
        )
        cached_profile = self._profile_cache(settings).load()
        catalog = _catalog_with_spotify_candidates(catalog, cached_profile)
        profile = self._request_profile(settings, request, cached_profile=cached_profile)
        service = AgenticRecommendationService(
            catalog=catalog,
            profile=profile,
            intent_parser=(
                (lambda prompt: parse_intent_with_agent(prompt, model=settings.openai_agent_model))
                if request.use_openai_agent
                else None
            ),
            agent_model=settings.openai_agent_model,
        )
        response = service.recommend(
            prompt=request.prompt,
            limit=request.limit,
            create_playlist=request.create_playlist,
            use_agent_orchestrator=request.use_openai_agent,
        )
        payload = response.to_dict()
        self._session_store(settings).put(
            _session_from_recommendation_payload(
                payload,
                user_id=profile.user_id,
                catalog_run_id=catalog_run_id,
                interaction_run_id=interaction_run_id,
            )
        )
        return payload

    def create_playlist(self, request: PlaylistCreateRequest) -> JsonDict:
        settings = self._settings()
        session_store = self._session_store(settings)
        session = session_store.get(request.session_id)
        if session is None:
            raise ApiNotFoundError(f"Recommendation session not found: {request.session_id}")
        invalid_track_ids = session.invalid_track_ids(tuple(request.track_ids))
        if invalid_track_ids:
            raise ApiValidationError(
                "Track IDs were not recommended for this session: " + ", ".join(invalid_track_ids)
            )
        playlist_service = PlaylistService(
            spotify_client=self._spotify_user_client(settings),
            store=self._playlist_store(settings),
            user_id=settings.spotify_demo_user_id,
        )
        result = playlist_service.create_playlist(
            session_id=request.session_id,
            name=request.name,
            description=request.description,
            track_ids=tuple(request.track_ids),
            public=request.public,
        )
        if not result.idempotent_replay or session.playlist_result is None:
            session_store.update_playlist_result(
                request.session_id,
                PlaylistResult(
                    playlist_id=result.playlist_id,
                    url=result.url,
                    requested_track_ids=tuple(request.track_ids),
                    tracks_added=result.tracks_added,
                    snapshot_id=result.snapshot_id,
                    idempotent_replay=result.idempotent_replay,
                    partial_failures=result.partial_failures,
                ),
            )
        return result.to_dict()

    def record_feedback(self, request: FeedbackRequest) -> JsonDict:
        settings = self._settings()
        session_store = self._session_store(settings)
        session = session_store.get(request.session_id)
        if session is None:
            raise ApiNotFoundError(f"Recommendation session not found: {request.session_id}")
        invalid_track_ids = session.invalid_track_ids((request.track_id,))
        if invalid_track_ids:
            raise ApiValidationError(
                "Track IDs were not recommended for this session: " + ", ".join(invalid_track_ids)
            )
        feedback_service = FeedbackService(store=self._feedback_store(settings))
        event = feedback_service.record_feedback(
            session_id=request.session_id,
            track_id=request.track_id,
            event_type=request.event_type,
            metadata=request.metadata,
        )
        return {"event_id": event.event_id, "status": "recorded"}

    def sync_profile(self, request: ProfileSyncRequest) -> JsonDict:
        settings = self._settings()
        sync_service = self._profile_sync_service(settings)
        return sync_service.sync_profile(
            top_limit=request.top_limit,
            saved_limit=request.saved_limit,
            top_time_ranges=tuple(request.top_time_ranges),
            include_playlists=request.include_playlists,
            playlist_limit=request.playlist_limit,
            playlist_track_limit=request.playlist_track_limit,
            playlist_ids=tuple(request.playlist_ids),
            include_recently_played=request.include_recently_played,
            recently_played_limit=request.recently_played_limit,
            market=request.market,
        ).to_dict()

    def get_profile_status(self) -> JsonDict:
        settings = self._settings()
        snapshot = self._profile_cache(settings).load()
        if snapshot is None:
            return {"present": False, "profile": None, "synced_at": None}
        return {
            "present": True,
            "profile": _profile_payload(snapshot.profile),
            "source": snapshot.source,
            "source_counts": snapshot.source_counts,
            "playlist_sources": list(snapshot.playlist_sources),
            "synced_at": snapshot.synced_at,
            "time_ranges": list(snapshot.time_ranges),
            "missing_optional_scopes": list(snapshot.missing_optional_scopes),
        }

    def _settings(self) -> Settings:
        try:
            return self.settings_loader()
        except ValueError as exc:
            raise ApiConfigurationError(str(exc)) from exc

    def _request_profile(
        self,
        settings: Settings,
        request: RecommendationRequest,
        *,
        cached_profile: ProfileSnapshot | None = None,
    ) -> UserTasteProfile:
        base_profile = (
            cached_profile.profile
            if cached_profile is not None
            else UserTasteProfile(
                user_id=(
                    request.demo_user_id
                    or settings.recommender_demo_user_id
                    or settings.spotify_demo_user_id
                )
            )
        )
        return UserTasteProfile(
            user_id=request.demo_user_id or base_profile.user_id,
            liked_track_ids=_merge_tuple(base_profile.liked_track_ids, request.liked_track_ids),
            known_track_ids=_merge_tuple(base_profile.known_track_ids, request.known_track_ids),
            liked_artist_names=_merge_tuple(
                base_profile.liked_artist_names,
                request.liked_artist_names,
            ),
            blocked_artist_names=_merge_tuple(
                base_profile.blocked_artist_names,
                request.blocked_artist_names,
            ),
            artist_affinity=base_profile.artist_affinity,
            track_affinity=base_profile.track_affinity,
        )

    def _profile_sync_service(self, settings: Settings) -> SpotifyProfileSyncService:
        return SpotifyProfileSyncService(
            spotify_client=self._spotify_user_client(settings),
            cache=self._profile_cache(settings),
            required_user_id=settings.spotify_demo_user_id,
        )

    def _profile_cache(self, settings: Settings) -> ProfileCache:
        if _use_dynamodb(settings, settings.users_table_name):
            return DynamoDBProfileCache(
                table_name=_required_table_name(
                    settings,
                    settings.users_table_name,
                    "USERS_TABLE_NAME",
                ),
                user_id=settings.spotify_demo_user_id,
                dynamodb_client=self._dynamodb_client(),
            )
        return JsonProfileCache(_state_path("RECOMMENDER_PROFILE_CACHE_PATH"))

    def _session_store(self, settings: Settings) -> RecommendationSessionStore:
        if _use_dynamodb(settings, settings.sessions_table_name):
            return DynamoDBRecommendationSessionStore(
                table_name=_required_table_name(
                    settings,
                    settings.sessions_table_name,
                    "SESSIONS_TABLE_NAME",
                ),
                dynamodb_client=self._dynamodb_client(),
            )
        return JsonRecommendationSessionStore(_state_path("RECOMMENDER_SESSION_STORE_PATH"))

    def _feedback_store(self, settings: Settings) -> JsonFeedbackStore | DynamoDBFeedbackStore:
        if _use_dynamodb(settings, settings.feedback_table_name):
            return DynamoDBFeedbackStore(
                table_name=_required_table_name(
                    settings,
                    settings.feedback_table_name,
                    "FEEDBACK_TABLE_NAME",
                ),
                dynamodb_client=self._dynamodb_client(),
            )
        return JsonFeedbackStore(_state_path("RECOMMENDER_FEEDBACK_STORE_PATH"))

    def _playlist_store(
        self,
        settings: Settings,
    ) -> JsonPlaylistRecordStore | DynamoDBPlaylistRecordStore:
        if _use_dynamodb(settings, settings.playlists_table_name):
            return DynamoDBPlaylistRecordStore(
                table_name=_required_table_name(
                    settings,
                    settings.playlists_table_name,
                    "PLAYLISTS_TABLE_NAME",
                ),
                dynamodb_client=self._dynamodb_client(),
            )
        return JsonPlaylistRecordStore(_state_path("RECOMMENDER_PLAYLIST_STORE_PATH"))

    def _dynamodb_client(self) -> Any:
        if self.dynamodb_client_factory is not None:
            return self.dynamodb_client_factory()
        import boto3

        return boto3.client("dynamodb")

    def _spotify_user_client(self, settings: Settings) -> SpotifyUserClient:
        if not settings.spotify_user_refresh_token:
            raise ApiConfigurationError("SPOTIFY_USER_REFRESH_TOKEN is required for this route.")
        return SpotifyUserClient(
            client_id=settings.spotify_client_id,
            client_secret=settings.spotify_client_secret,
            refresh_token=settings.spotify_user_refresh_token,
        )


def _state_path(env_name: str) -> Path:
    return Path(os.getenv(env_name, f"data/local/api_state/{env_name.lower()}.json"))


def _use_dynamodb(settings: Settings, table_name: str | None) -> bool:
    if settings.runtime_store_backend == "local":
        return False
    if settings.runtime_store_backend == "dynamodb":
        return True
    return bool(table_name)


def _required_table_name(
    settings: Settings,
    table_name: str | None,
    env_name: str,
) -> str:
    if table_name:
        return table_name
    if settings.runtime_store_backend == "dynamodb":
        raise ApiConfigurationError(f"{env_name} is required when RUNTIME_STORE_BACKEND=dynamodb.")
    raise ApiConfigurationError(f"{env_name} is required for DynamoDB runtime state.")


def _merge_tuple(existing: tuple[str, ...], extra: list[str]) -> tuple[str, ...]:
    seen = set(existing)
    merged = list(existing)
    for item in extra:
        if item in seen:
            continue
        seen.add(item)
        merged.append(item)
    return tuple(merged)


def _catalog_with_spotify_candidates(
    catalog: RecommenderCatalog,
    cached_profile: ProfileSnapshot | None,
) -> RecommenderCatalog:
    if cached_profile is None or not cached_profile.spotify_track_candidates:
        return catalog
    seen_track_ids = set(catalog.by_track_id)
    extra_tracks: list[CatalogTrack] = []
    for candidate in cached_profile.spotify_track_candidates:
        track = _spotify_candidate_to_catalog_track(candidate)
        if track is None or track.id in seen_track_ids:
            continue
        seen_track_ids.add(track.id)
        extra_tracks.append(track)
    if not extra_tracks:
        return catalog
    return RecommenderCatalog(tracks=(*catalog.tracks, *extra_tracks))


def _spotify_candidate_to_catalog_track(candidate: JsonDict) -> CatalogTrack | None:
    track_id = _optional_str(candidate.get("id"))
    if track_id is None:
        return None
    artist_names = _string_tuple(candidate.get("artist_names"))
    primary_artist_name = _optional_str(candidate.get("primary_artist_name")) or (
        artist_names[0] if artist_names else None
    )
    return CatalogTrack(
        id=track_id,
        name=_optional_str(candidate.get("name")) or track_id,
        artist_names=artist_names,
        primary_artist_name=primary_artist_name,
        explicit=bool(candidate.get("explicit") or False),
        popularity=_optional_int(candidate.get("popularity")),
        spotify_url=_optional_str(candidate.get("spotify_url")),
    )


def _string_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list | tuple):
        return tuple(str(item) for item in value if item is not None)
    return (str(value),)


def _optional_str(value: object) -> str | None:
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


def _profile_payload(profile: UserTasteProfile) -> JsonDict:
    payload: JsonDict = {
        "user_id": profile.user_id,
        "liked_track_ids": list(profile.liked_track_ids),
        "known_track_ids": list(profile.known_track_ids),
        "liked_artist_names": list(profile.liked_artist_names),
        "blocked_artist_names": list(profile.blocked_artist_names),
    }
    if profile.artist_affinity is not None:
        payload["artist_affinity"] = profile.artist_affinity
    if profile.track_affinity is not None:
        payload["track_affinity"] = profile.track_affinity
    return payload


def _session_from_recommendation_payload(
    payload: JsonDict,
    *,
    user_id: str,
    catalog_run_id: str,
    interaction_run_id: str | None,
) -> RecommendationSession:
    now = datetime.now(UTC).isoformat()
    recommendations = tuple(
        dict(item) for item in payload.get("recommendations", []) if isinstance(item, dict)
    )
    return RecommendationSession(
        session_id=str(payload["session_id"]),
        user_id=user_id,
        prompt=str(payload["prompt"]),
        intent=dict(payload.get("intent") or {}),
        recommended_track_ids=tuple(
            str(item["track"]["id"])
            for item in recommendations
            if isinstance(item.get("track"), dict) and item["track"].get("id")
        ),
        recommendations=recommendations,
        catalog_run_id=catalog_run_id,
        interaction_run_id=interaction_run_id,
        playlist_candidate=(
            dict(payload["playlist_candidate"])
            if isinstance(payload.get("playlist_candidate"), dict)
            else None
        ),
        created_at=now,
        updated_at=now,
    )
