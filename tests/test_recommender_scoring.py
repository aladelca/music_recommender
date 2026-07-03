from __future__ import annotations

from music_recommender.recommender.models import (
    AudioFeatures,
    CatalogTrack,
    MoodIntent,
    UserTasteProfile,
)
from music_recommender.recommender.scoring import rank_recommendations


def test_rank_recommendations_prefers_cheerful_taste_aligned_tracks_for_breakup() -> None:
    tracks = [
        catalog_track(
            "sunny",
            "Sunny Recovery",
            "Dua Lipa",
            popularity=82,
            valence=0.93,
            energy=0.82,
            danceability=0.86,
        ),
        catalog_track(
            "sad",
            "Sad Ballad",
            "Dua Lipa",
            popularity=90,
            valence=0.12,
            energy=0.22,
            danceability=0.28,
        ),
        catalog_track(
            "blocked",
            "Blocked Party",
            "Blocked Artist",
            popularity=99,
            valence=0.96,
            energy=0.9,
            danceability=0.9,
        ),
        catalog_track(
            "explicit",
            "Explicit Lift",
            "Friendly Artist",
            popularity=70,
            explicit=True,
            valence=0.9,
            energy=0.8,
            danceability=0.8,
        ),
    ]
    intent = MoodIntent.cheer_up_after_breakup(
        allow_explicit=False,
        blocked_artist_names=("Blocked Artist",),
    )
    profile = UserTasteProfile(
        user_id="demo",
        liked_artist_names=("Dua Lipa",),
        known_track_ids=("sad",),
    )

    ranked = rank_recommendations(tracks, intent=intent, profile=profile, limit=3)

    assert [candidate.track.id for candidate in ranked] == ["sunny", "sad"]
    assert ranked[0].score.total > ranked[1].score.total
    assert ranked[0].score.mood_fit > ranked[1].score.mood_fit
    assert "cheer-up mood" in ranked[0].explanation
    assert "Dua Lipa" in ranked[0].explanation


def test_rank_recommendations_deduplicates_and_limits_repeat_artists() -> None:
    tracks = [
        catalog_track("track-1", "First", "Artist A", popularity=75),
        catalog_track("track-1", "First Duplicate", "Artist A", popularity=99),
        catalog_track("track-2", "Second", "Artist A", popularity=74),
        catalog_track("track-3", "Third", "Artist B", popularity=65),
    ]
    intent = MoodIntent.cheer_up_after_breakup()
    profile = UserTasteProfile(user_id="demo")

    ranked = rank_recommendations(
        tracks,
        intent=intent,
        profile=profile,
        limit=3,
        max_tracks_per_artist=1,
    )

    assert [candidate.track.id for candidate in ranked] == ["track-1", "track-3"]
    assert len({candidate.track.id for candidate in ranked}) == len(ranked)


def test_rank_recommendations_handles_empty_candidate_sets() -> None:
    assert (
        rank_recommendations(
            [],
            intent=MoodIntent.cheer_up_after_breakup(),
            profile=UserTasteProfile(user_id="demo"),
            limit=10,
        )
        == []
    )


def catalog_track(
    track_id: str,
    name: str,
    artist: str,
    *,
    popularity: int = 50,
    explicit: bool = False,
    valence: float = 0.8,
    energy: float = 0.75,
    danceability: float = 0.7,
) -> CatalogTrack:
    return CatalogTrack(
        id=track_id,
        name=name,
        artist_names=(artist,),
        primary_artist_name=artist,
        explicit=explicit,
        popularity=popularity,
        spotify_url=f"https://open.spotify.com/track/{track_id}",
        seed_artist=artist,
        audio_features=AudioFeatures(
            spotify_track_id=track_id,
            danceability=danceability,
            energy=energy,
            valence=valence,
        ),
    )
