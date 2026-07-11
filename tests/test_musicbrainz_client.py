from __future__ import annotations

import urllib.parse

import httpx
import pytest

from music_recommender.sources.http import ApiHttpClient
from music_recommender.sources.musicbrainz import (
    MusicBrainzClient,
    MusicBrainzUnavailableError,
)


def test_musicbrainz_artist_search_uses_contactable_user_agent_and_bounded_query() -> None:
    captured_request: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_request
        captured_request = request
        return httpx.Response(
            200,
            json={
                "artists": [
                    {
                        "id": "8ab7aa79-24a4-4a5f-b2c6-3e3c2c7af95c",
                        "name": "Portishead",
                        "sort-name": "Portishead",
                        "country": "GB",
                        "disambiguation": "Bristol trip hop group",
                        "score": 100,
                        "tags": [{"name": "trip hop", "count": 8}],
                    }
                ]
            },
            request=request,
        )

    client = build_client(httpx.MockTransport(handler))

    results = client.search("Portishead", entity_type="artist", limit=5)

    assert captured_request is not None
    params = urllib.parse.parse_qs(captured_request.url.query.decode("utf-8"))
    assert captured_request.url.path == "/ws/2/artist"
    assert captured_request.headers["user-agent"] == ("OutsideTheLoop/0.1.0 (contact@example.com)")
    assert params == {"fmt": ["json"], "limit": ["5"], "query": ['artist:"Portishead"']}
    assert results[0].to_dict() == {
        "mbid": "8ab7aa79-24a4-4a5f-b2c6-3e3c2c7af95c",
        "entity_type": "artist",
        "name": "Portishead",
        "artist_credit": [],
        "release_data": {
            "country": "GB",
            "disambiguation": "Bristol trip hop group",
            "tags": ["trip hop"],
        },
        "isrcs": [],
        "source": "musicbrainz",
    }


def test_musicbrainz_recording_search_normalizes_artist_credit_release_and_isrc() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "recordings": [
                    {
                        "id": "fbe4eb72-f5d9-4c8d-a7e2-5f64184f1d20",
                        "title": "Roads",
                        "first-release-date": "1994-08-22",
                        "artist-credit": [
                            {
                                "name": "Portishead",
                                "artist": {
                                    "id": "8ab7aa79-24a4-4a5f-b2c6-3e3c2c7af95c",
                                    "name": "Portishead",
                                },
                            }
                        ],
                        "releases": [
                            {
                                "id": "47b19450-5a9f-4d1f-b7ef-3bb2930344b0",
                                "title": "Dummy",
                                "date": "1994-08-22",
                                "country": "GB",
                            }
                        ],
                        "isrcs": ["GBAQT9400001"],
                    }
                ]
            },
            request=request,
        )

    result = build_client(httpx.MockTransport(handler)).search(
        "Roads",
        entity_type="recording",
        limit=10,
    )[0]

    assert result.name == "Roads"
    assert result.artist_credit == (
        {
            "mbid": "8ab7aa79-24a4-4a5f-b2c6-3e3c2c7af95c",
            "name": "Portishead",
        },
    )
    assert result.release_data["first_release_date"] == "1994-08-22"
    assert result.release_data["releases"] == [
        {
            "mbid": "47b19450-5a9f-4d1f-b7ef-3bb2930344b0",
            "title": "Dummy",
            "date": "1994-08-22",
            "country": "GB",
        }
    ]
    assert result.isrcs == ("GBAQT9400001",)


def test_musicbrainz_errors_are_redacted() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            503,
            json={"error": "private-upstream-detail"},
            request=request,
        )

    client = build_client(httpx.MockTransport(handler), max_retries=0)

    with pytest.raises(MusicBrainzUnavailableError) as error:
        client.search("Portishead", entity_type="artist")

    assert "private-upstream-detail" not in str(error.value)
    assert "Portishead" not in str(error.value)


def build_client(
    transport: httpx.MockTransport,
    *,
    max_retries: int = 3,
) -> MusicBrainzClient:
    return MusicBrainzClient(
        contact_email="contact@example.com",
        app_version="0.1.0",
        http=ApiHttpClient(
            client=httpx.Client(
                transport=transport,
                base_url="https://musicbrainz.org/ws/2",
            ),
            max_retries=max_retries,
            sleep=lambda _: None,
        ),
    )
