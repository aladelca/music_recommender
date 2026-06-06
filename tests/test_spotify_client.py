from __future__ import annotations

import httpx

from music_recommender.models import SpotifyArtist
from music_recommender.sources.http import ApiHttpClient
from music_recommender.sources.spotify import SpotifyClient


def build_client(api_transport: httpx.MockTransport) -> SpotifyClient:
    auth_transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={"access_token": "token", "expires_in": 3600},
            request=request,
        )
    )
    return SpotifyClient(
        client_id="client",
        client_secret="secret",
        auth_http=ApiHttpClient(
            client=httpx.Client(transport=auth_transport, base_url="https://accounts.spotify.com")
        ),
        api_http=ApiHttpClient(
            client=httpx.Client(transport=api_transport, base_url="https://api.spotify.com/v1"),
            sleep=lambda _: None,
        ),
    )


def test_search_artist_prefers_exact_match() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert spotify_path(request) == "/search"
        return httpx.Response(
            200,
            json={
                "artists": {
                    "items": [
                        {"id": "wrong", "name": "Billie Holiday", "popularity": 90, "genres": []},
                        {"id": "right", "name": "Billie Eilish", "popularity": 70, "genres": []},
                    ]
                }
            },
            request=request,
        )

    client = build_client(httpx.MockTransport(handler))

    artist = client.search_artist("Billie Eilish")

    assert artist is not None
    assert artist.id == "right"


def test_album_and_track_pagination_and_track_metadata() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = spotify_path(request)
        if path == "/artists/artist-1/albums":
            offset = request.url.params.get("offset")
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": f"album-{offset}",
                            "name": f"Album {offset}",
                            "album_type": "album",
                            "release_date": "2024",
                            "total_tracks": 1,
                        }
                    ],
                    "next": "next" if offset == "0" else None,
                },
                request=request,
            )
        if path == "/albums/album-0/tracks":
            return httpx.Response(
                200, json={"items": [{"id": "track-1"}], "next": None}, request=request
            )
        if path == "/tracks/track-1":
            return httpx.Response(
                200,
                json={
                    "id": "track-1",
                    "name": "Song",
                    "duration_ms": 120000,
                    "explicit": False,
                    "popularity": 50,
                    "external_ids": {"isrc": "ABC"},
                    "external_urls": {"spotify": "https://spotify/track-1"},
                    "artists": [{"name": "Artist"}],
                    "album": {"id": "album-0", "name": "Album 0", "release_date": "2024"},
                },
                request=request,
            )
        return httpx.Response(404, request=request)

    client = build_client(httpx.MockTransport(handler))
    artist = SpotifyArtist(
        id="artist-1",
        name="Artist",
        popularity=10,
        genres=[],
        spotify_url=None,
        seed_artist="Artist",
        raw={"id": "artist-1", "name": "Artist"},
    )

    albums = client.iter_artist_albums(artist)
    track_ids = client.iter_album_track_ids("album-0")
    track = client.get_track("track-1", seed_artist="Artist", spotify_artist_id="artist-1")

    assert [album.id for album in albums] == ["album-0", "album-10"]
    assert track_ids == ["track-1"]
    assert track.isrc == "ABC"


def test_audio_features_unavailable_is_non_fatal() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if spotify_path(request) == "/audio-features/track-1":
            return httpx.Response(403, json={"error": "forbidden"}, request=request)
        return httpx.Response(404, request=request)

    client = build_client(httpx.MockTransport(handler))

    record = client.get_audio_features("track-1", "now")

    assert record.status == "unavailable"
    assert record.error_code == 403


def spotify_path(request: httpx.Request) -> str:
    return request.url.path.removeprefix("/v1")


def test_retries_429_using_retry_after() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "0"}, request=request)
        return httpx.Response(
            200,
            json={"artists": {"items": [{"id": "artist-1", "name": "Artist", "popularity": 1}]}},
            request=request,
        )

    client = build_client(httpx.MockTransport(handler))

    artist = client.search_artist("Artist")

    assert artist is not None
    assert calls == 2
