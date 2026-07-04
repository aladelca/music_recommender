from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

TopTimeRange = Literal["short_term", "medium_term", "long_term"]


def _default_top_time_ranges() -> list[TopTimeRange]:
    return ["medium_term"]


class ConfigPresence(BaseModel):
    aws_region: str
    api_key_required: bool
    aws_secrets_prefix_present: bool
    music_recommender_bucket_present: bool
    openai_api_key_present: bool
    recommender_data_mode: str
    recommender_data_root_present: bool
    spotify_client_id_present: bool
    spotify_client_secret_present: bool
    spotify_user_refresh_token_present: bool


class HealthResponse(BaseModel):
    status: Literal["ok"]
    version: str
    config: ConfigPresence


class RecommendationRequest(BaseModel):
    prompt: str = Field(min_length=1)
    limit: int = Field(default=10, ge=1, le=50)
    create_playlist: bool = False
    use_openai_agent: bool = False
    catalog_run_id: str | None = None
    interaction_run_id: str | None = None
    demo_user_id: str | None = None
    liked_artist_names: list[str] = Field(default_factory=list)
    liked_track_ids: list[str] = Field(default_factory=list)
    known_track_ids: list[str] = Field(default_factory=list)
    blocked_artist_names: list[str] = Field(default_factory=list)


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
