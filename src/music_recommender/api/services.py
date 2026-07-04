from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from music_recommender.agents.intent import parse_intent_with_agent
from music_recommender.agents.orchestrator import AgenticRecommendationService
from music_recommender.api.errors import ApiConfigurationError
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
from music_recommender.recommender.models import UserTasteProfile
from music_recommender.recommender.playlists import JsonPlaylistRecordStore, PlaylistService
from music_recommender.recommender.profile import (
    JsonProfileCache,
    SpotifyProfileSyncService,
)
from music_recommender.sources.spotify_user import SpotifyUserClient


class DemoApiService:
    def __init__(
        self,
        *,
        settings_loader: Callable[[], Settings] = load_settings,
    ) -> None:
        self.settings_loader = settings_loader

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
        profile = self._request_profile(settings, request)
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
        return service.recommend(
            prompt=request.prompt,
            limit=request.limit,
            create_playlist=request.create_playlist,
            use_agent_orchestrator=request.use_openai_agent,
        ).to_dict()

    def create_playlist(self, request: PlaylistCreateRequest) -> JsonDict:
        settings = self._settings()
        playlist_service = PlaylistService(
            spotify_client=self._spotify_user_client(settings),
            store=JsonPlaylistRecordStore(_state_path("RECOMMENDER_PLAYLIST_STORE_PATH")),
            user_id=settings.spotify_demo_user_id,
        )
        return playlist_service.create_playlist(
            session_id=request.session_id,
            name=request.name,
            description=request.description,
            track_ids=tuple(request.track_ids),
            public=request.public,
        ).to_dict()

    def record_feedback(self, request: FeedbackRequest) -> JsonDict:
        feedback_service = FeedbackService(
            store=JsonFeedbackStore(_state_path("RECOMMENDER_FEEDBACK_STORE_PATH"))
        )
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
        snapshot = JsonProfileCache(_state_path("RECOMMENDER_PROFILE_CACHE_PATH")).load()
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
    ) -> UserTasteProfile:
        cached = JsonProfileCache(_state_path("RECOMMENDER_PROFILE_CACHE_PATH")).load()
        base_profile = (
            cached.profile
            if cached is not None
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
            cache=JsonProfileCache(_state_path("RECOMMENDER_PROFILE_CACHE_PATH")),
            required_user_id=settings.spotify_demo_user_id,
        )

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


def _merge_tuple(existing: tuple[str, ...], extra: list[str]) -> tuple[str, ...]:
    seen = set(existing)
    merged = list(existing)
    for item in extra:
        if item in seen:
            continue
        seen.add(item)
        merged.append(item)
    return tuple(merged)


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
