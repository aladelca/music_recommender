from __future__ import annotations

from dataclasses import dataclass

from music_recommender.storage.protocols import CandidateEdgeRecord, MusicEntityRecord


@dataclass(frozen=True)
class AudioFeatures:
    spotify_track_id: str
    danceability: float | None = None
    energy: float | None = None
    valence: float | None = None
    acousticness: float | None = None
    instrumentalness: float | None = None
    tempo: float | None = None


@dataclass(frozen=True)
class CatalogTrack:
    id: str
    name: str
    artist_names: tuple[str, ...]
    primary_artist_name: str | None
    explicit: bool
    popularity: int | None
    spotify_url: str | None
    seed_artist: str | None = None
    audio_features: AudioFeatures | None = None
    lyrics_sentiment_label: str | None = None
    lyrics_positive_score: float | None = None
    lyrics_negative_score: float | None = None
    lyrics_neutral_score: float | None = None
    interaction_count: int = 0
    max_implicit_rating: float | None = None


@dataclass(frozen=True)
class RecommenderCatalog:
    tracks: tuple[CatalogTrack, ...]

    @property
    def by_track_id(self) -> dict[str, CatalogTrack]:
        return {track.id: track for track in self.tracks}


@dataclass(frozen=True)
class MoodIntent:
    label: str
    target_valence: float
    target_energy: float
    target_danceability: float
    allow_explicit: bool = True
    blocked_artist_names: tuple[str, ...] = ()

    @classmethod
    def cheer_up_after_breakup(
        cls,
        *,
        allow_explicit: bool = True,
        blocked_artist_names: tuple[str, ...] = (),
    ) -> MoodIntent:
        return cls(
            label="cheer-up",
            target_valence=0.88,
            target_energy=0.78,
            target_danceability=0.76,
            allow_explicit=allow_explicit,
            blocked_artist_names=blocked_artist_names,
        )


@dataclass(frozen=True)
class UserTasteProfile:
    user_id: str
    liked_track_ids: tuple[str, ...] = ()
    known_track_ids: tuple[str, ...] = ()
    liked_artist_names: tuple[str, ...] = ()
    blocked_artist_names: tuple[str, ...] = ()
    artist_affinity: dict[str, float] | None = None
    track_affinity: dict[str, float] | None = None


@dataclass(frozen=True)
class ScoreBreakdown:
    mood_fit: float
    taste_affinity: float
    novelty_bonus: float
    popularity_prior: float
    diversity_penalty: float
    total: float


@dataclass(frozen=True)
class RecommendationCandidate:
    track: CatalogTrack
    score: ScoreBreakdown
    explanation: str


@dataclass(frozen=True)
class DiscoveryRankingPreferences:
    blocked_artist_mbids: tuple[str, ...] = ()
    blocked_recording_mbids: tuple[str, ...] = ()


@dataclass(frozen=True)
class DiscoveryScoreBreakdown:
    prompt_tag_fit: float
    seed_bridge_strength: float
    discovery_value: float
    evidence_quality: float
    total: float


@dataclass(frozen=True)
class RankedDiscoveryCandidate:
    entity: MusicEntityRecord
    edges: tuple[CandidateEdgeRecord, ...]
    score: DiscoveryScoreBreakdown
    ranking_version: str
