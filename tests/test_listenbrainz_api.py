from __future__ import annotations

import urllib.parse

import httpx

from music_recommender.sources.http import ApiHttpClient
from music_recommender.sources.listenbrainz_api import ListenBrainzApiClient


def test_artist_radio_normalizes_candidates_and_rate_limit_headers() -> None:
    captured: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured
        captured = request
        return httpx.Response(
            200,
            headers={
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset-In": "2.5",
            },
            json={
                "payload": [
                    {
                        "recording_mbid": "f3bba4cd-8018-468b-902e-bc8f029593e5",
                        "similar_artist_mbid": "10adbe5c-2788-4578-a28c-1f9b1dd3b0de",
                        "similar_artist_name": "Massive Attack",
                        "total_listen_count": 232361,
                    }
                ]
            },
            request=request,
        )

    batch = build_client(httpx.MockTransport(handler)).artist_radio(
        "8ab7aa79-24a4-4a5f-b2c6-3e3c2c7af95c",
        mode="medium",
        max_similar_artists=10,
        max_recordings_per_artist=5,
    )

    assert captured is not None
    params = urllib.parse.parse_qs(captured.url.query.decode("utf-8"))
    assert captured.url.path == ("/1/lb-radio/artist/8ab7aa79-24a4-4a5f-b2c6-3e3c2c7af95c")
    assert params == {
        "mode": ["medium"],
        "max_similar_artists": ["10"],
        "max_recordings_per_artist": ["5"],
        "pop_begin": ["5"],
        "pop_end": ["80"],
    }
    assert batch.retry_after_seconds == 2.5
    assert batch.candidates[0].to_dict() == {
        "recording_mbid": "f3bba4cd-8018-468b-902e-bc8f029593e5",
        "source_adapter": "listenbrainz_artist_radio",
        "similar_artist_mbid": "10adbe5c-2788-4578-a28c-1f9b1dd3b0de",
        "similar_artist_name": "Massive Attack",
        "total_listen_count": 232361,
        "tags": [],
        "source_facts": {"mode": "medium"},
    }


def test_tag_radio_sends_repeated_bounded_tags() -> None:
    captured: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured
        captured = request
        return httpx.Response(
            200,
            json=[
                {
                    "recording_mbid": "f3bba4cd-8018-468b-902e-bc8f029593e5",
                    "percent": 71.9,
                    "source": "release-group",
                    "tag_count": 5,
                }
            ],
            request=request,
        )

    batch = build_client(httpx.MockTransport(handler)).tag_radio(
        ("trip hop", "downtempo"),
        count=25,
    )

    assert captured is not None
    params = urllib.parse.parse_qs(captured.url.query.decode("utf-8"))
    assert captured.url.path == "/1/lb-radio/tags"
    assert params["tag"] == ["trip hop", "downtempo"]
    assert params["operator"] == ["OR"]
    assert params["count"] == ["25"]
    assert batch.candidates[0].source_adapter == "listenbrainz_tag_radio"
    assert batch.candidates[0].tags == ("trip hop", "downtempo")
    assert batch.candidates[0].source_facts == {
        "operator": "OR",
        "percent": 71.9,
        "source": "release-group",
        "tag_count": 5,
    }


def test_bulk_recording_metadata_normalizes_artist_tags_and_release() -> None:
    captured: httpx.Request | None = None
    recording_mbid = "e97f805a-ab48-4c52-855e-07049142113d"

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured
        captured = request
        return httpx.Response(
            200,
            json={
                recording_mbid: {
                    "artist": {
                        "name": "Portishead",
                        "artists": [
                            {
                                "artist_mbid": "8ab7aa79-24a4-4a5f-b2c6-3e3c2c7af95c",
                                "name": "Portishead",
                            }
                        ],
                    },
                    "recording": {
                        "name": "Roads",
                        "isrcs": ["GBF089400123"],
                        "first_release_date": "1994-08-22",
                        "length": 305000,
                    },
                    "tag": {
                        "recording": [
                            {"tag": "trip hop", "count": 8},
                            {"tag": "electronic", "count": 3},
                        ]
                    },
                    "release": {
                        "mbid": "76df3287-6cda-33eb-8e9a-044b5e15ffdd",
                        "name": "Dummy",
                        "year": 1994,
                    },
                }
            },
            request=request,
        )

    metadata = build_client(httpx.MockTransport(handler)).recording_metadata((recording_mbid,))

    assert captured is not None
    assert captured.url.path == "/1/metadata/recording/"
    assert captured.read() == (
        b'{"recording_mbids":["e97f805a-ab48-4c52-855e-07049142113d"],"inc":"artist tag release"}'
    )
    assert metadata.records[0].recording_mbid == recording_mbid
    assert metadata.records[0].name == "Roads"
    assert metadata.records[0].isrcs == ("GBF089400123",)
    assert metadata.records[0].artist_credit == (
        {
            "mbid": "8ab7aa79-24a4-4a5f-b2c6-3e3c2c7af95c",
            "name": "Portishead",
        },
    )
    assert metadata.records[0].tags == ("trip hop", "electronic")
    assert metadata.records[0].release_data == {
        "mbid": "76df3287-6cda-33eb-8e9a-044b5e15ffdd",
        "name": "Dummy",
        "year": 1994,
        "recording_first_release_date": "1994-08-22",
        "duration_ms": 305000,
    }


def test_listenbrainz_retries_retry_after_without_user_token() -> None:
    calls = 0
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "0.5"}, request=request)
        return httpx.Response(200, json=[], request=request)

    client = build_client(
        httpx.MockTransport(handler),
        max_retries=1,
        sleep=sleeps.append,
    )

    client.artist_radio("8ab7aa79-24a4-4a5f-b2c6-3e3c2c7af95c")

    assert calls == 2
    assert sleeps == [0.5]


def build_client(
    transport: httpx.MockTransport,
    *,
    max_retries: int = 3,
    sleep: object | None = None,
) -> ListenBrainzApiClient:
    return ListenBrainzApiClient(
        contact_email="contact@example.com",
        app_version="0.1.0",
        http=ApiHttpClient(
            client=httpx.Client(
                transport=transport,
                base_url="https://api.listenbrainz.org",
            ),
            max_retries=max_retries,
            sleep=sleep if callable(sleep) else (lambda _: None),
        ),
    )
