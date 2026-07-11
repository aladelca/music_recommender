from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

TopTimeRange = Literal["short_term", "medium_term", "long_term"]


def _default_top_time_ranges() -> list[TopTimeRange]:
    return ["medium_term"]


class ConfigPresence(BaseModel):
    aws_region: str
    api_key_required: bool
    aws_secrets_prefix_present: bool
    dynamodb_feedback_table_present: bool
    dynamodb_playlists_table_present: bool
    dynamodb_sessions_table_present: bool
    dynamodb_users_table_present: bool
    music_recommender_bucket_present: bool
    openai_api_key_present: bool
    recommender_data_mode: str
    recommender_data_root_present: bool
    runtime_store_backend: str
    spotify_client_id_present: bool
    spotify_client_secret_present: bool
    spotify_user_refresh_token_present: bool


class HealthResponse(BaseModel):
    status: Literal["ok"]
    version: str


class ReadinessResponse(BaseModel):
    status: Literal["ready", "unavailable"]


class SeedSelectionRequest(BaseModel):
    entity_type: Literal["artist", "recording"]
    mbid: UUID


class ReplaceSeedsRequest(BaseModel):
    seeds: list[SeedSelectionRequest] = Field(min_length=1, max_length=5)


class RecommendationRequest(BaseModel):
    prompt: str = Field(min_length=1)
    limit: int = Field(default=10, ge=1, le=50)
    create_playlist: bool = False
    playlist_name: str | None = Field(default=None, min_length=1)
    playlist_public: bool = True
    use_openai_agent: bool = False
    catalog_run_id: str | None = None
    interaction_run_id: str | None = None
    demo_user_id: str | None = None
    liked_artist_names: list[str] = Field(default_factory=list)
    liked_track_ids: list[str] = Field(default_factory=list)
    known_track_ids: list[str] = Field(default_factory=list)
    blocked_artist_names: list[str] = Field(default_factory=list)


class ProductRecommendationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(min_length=2, max_length=500)
    adventure: Literal["familiar", "balanced", "adventurous"] = "balanced"
    allow_explicit: bool = True
    seed_ids: list[UUID] = Field(min_length=1, max_length=5)


class ReviewRecommendationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recording_mbids: list[UUID] = Field(min_length=1, max_length=10)
    playlist_name: str = Field(min_length=1, max_length=100)
    public: bool = False


class ProductPlaylistExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=300)
    public: bool
    recording_mbids: list[UUID] = Field(min_length=1, max_length=20)


class ProductFeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recording_mbid: UUID
    event_type: Literal["like", "dislike", "hide_artist", "save", "skip"]
    reason: str | None = Field(default=None, min_length=1, max_length=200)


class SessionEvaluationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    comparison: Literal["better", "same", "worse", "not_sure"]
    explanation_usefulness: int = Field(ge=1, le=5)
    novelty_quality: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, min_length=1, max_length=1_000)


class AccountDeletionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmation: Literal["DELETE"]


class PlaylistCreateRequest(BaseModel):
    session_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str = ""
    track_ids: list[str] = Field(min_length=1)
    public: bool = False


FeedbackEventType = Literal["like", "dislike", "hide_artist", "save", "skip", "refine"]


class FeedbackRequest(BaseModel):
    session_id: str = Field(min_length=1)
    track_id: str = Field(min_length=1)
    event_type: FeedbackEventType
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProfileSyncRequest(BaseModel):
    top_limit: int = Field(default=20, ge=1, le=50)
    saved_limit: int = Field(default=20, ge=1, le=50)
    top_time_ranges: list[TopTimeRange] = Field(default_factory=_default_top_time_ranges)
    include_playlists: bool = True
    playlist_limit: int = Field(default=10, ge=0, le=50)
    playlist_track_limit: int = Field(default=50, ge=0, le=500)
    playlist_ids: list[str] = Field(default_factory=list)
    include_recently_played: bool = False
    recently_played_limit: int = Field(default=20, ge=1, le=50)
    market: str | None = None
