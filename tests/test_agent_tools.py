from __future__ import annotations

import json

from music_recommender.agents.intent import ParsedMoodIntent
from music_recommender.agents.tools import (
    AgentToolContext,
    build_agent_tools,
    load_catalog_candidates_payload,
    rank_recommendations_payload,
)
from music_recommender.recommender.models import (
    AudioFeatures,
    CatalogTrack,
    RecommenderCatalog,
    UserTasteProfile,
)


def test_rank_recommendations_payload_is_json_safe_and_catalog_backed() -> None:
    context = AgentToolContext(
        catalog=RecommenderCatalog(
            tracks=(
                catalog_track("sunny", "Sunny Recovery", "Dua Lipa", valence=0.93),
                catalog_track("sad", "Sad Ballad", "Dua Lipa", valence=0.12),
            )
        ),
        profile=UserTasteProfile(user_id="demo", liked_artist_names=("Dua Lipa",)),
    )
    intent = ParsedMoodIntent.cheer_up_after_breakup()

    payload = rank_recommendations_payload(context, intent=intent, limit=2)

    assert payload["track_ids"] == ["sunny", "sad"]
    assert payload["tracks"][0]["id"] == "sunny"
    assert payload["tracks"][0]["score"]["total"] > payload["tracks"][1]["score"]["total"]
    json.dumps(payload)


def test_load_catalog_candidates_payload_returns_bounded_catalog_summary() -> None:
    context = AgentToolContext(
        catalog=RecommenderCatalog(
            tracks=(
                catalog_track("track-1", "One", "Artist A"),
                catalog_track("track-2", "Two", "Artist B"),
            )
        ),
        profile=UserTasteProfile(user_id="demo"),
    )

    payload = load_catalog_candidates_payload(context, limit=1)

    assert payload == {
        "count": 1,
        "tracks": [
            {
                "artist_names": ["Artist A"],
                "explicit": False,
                "id": "track-1",
                "name": "One",
                "popularity": 80,
                "spotify_url": "https://open.spotify.com/track/track-1",
            }
        ],
    }


def test_build_agent_tools_exposes_expected_sdk_tools() -> None:
    context = AgentToolContext(
        catalog=RecommenderCatalog(tracks=()),
        profile=UserTasteProfile(user_id="demo"),
    )

    tools = build_agent_tools(context)

    assert [tool.name for tool in tools] == [
        "load_user_profile",
        "load_catalog_candidates",
        "rank_catalog_recommendations",
    ]


def catalog_track(
    track_id: str,
    name: str,
    artist: str,
    *,
    valence: float = 0.8,
) -> CatalogTrack:
    return CatalogTrack(
        id=track_id,
        name=name,
        artist_names=(artist,),
        primary_artist_name=artist,
        explicit=False,
        popularity=80,
        spotify_url=f"https://open.spotify.com/track/{track_id}",
        audio_features=AudioFeatures(
            spotify_track_id=track_id,
            danceability=0.82,
            energy=0.8,
            valence=valence,
        ),
    )
