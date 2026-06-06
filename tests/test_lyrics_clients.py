from __future__ import annotations

import httpx

from music_recommender.models import SpotifyTrack
from music_recommender.sources.http import ApiHttpClient
from music_recommender.sources.lrclib import LrcLibClient
from music_recommender.sources.lyrics_ovh import LyricsOvhClient


def make_track() -> SpotifyTrack:
    return SpotifyTrack(
        id="track-1",
        name="Song",
        duration_ms=120000,
        explicit=False,
        popularity=10,
        isrc="ABC",
        album_id="album-1",
        album_name="Album",
        album_release_date="2024",
        artist_names=["Artist"],
        primary_artist_name="Artist",
        spotify_url="https://spotify/track-1",
        seed_artist="Artist",
        spotify_artist_id="artist-1",
        raw={},
    )


def test_lrclib_hit() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "id": 1,
                "trackName": "Song",
                "artistName": "Artist",
                "albumName": "Album",
                "duration": 120,
                "instrumental": False,
                "plainLyrics": "line",
                "syncedLyrics": "[00:01] line",
            },
            request=request,
        )
    )
    client = LrcLibClient(
        ApiHttpClient(client=httpx.Client(transport=transport, base_url="https://lrclib.net/api"))
    )

    record = client.get_lyrics(make_track(), "now")

    assert record.match_status == "hit"
    assert record.plain_lyrics == "line"
    assert record.lrclib_id == 1


def test_lrclib_miss() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(404, request=request))
    client = LrcLibClient(
        ApiHttpClient(client=httpx.Client(transport=transport, base_url="https://lrclib.net/api"))
    )

    record = client.get_lyrics(make_track(), "now")

    assert record.match_status == "miss"


def test_lyrics_ovh_hit_and_miss() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/Song"):
            return httpx.Response(200, json={"lyrics": "fallback"}, request=request)
        return httpx.Response(404, request=request)

    client = LyricsOvhClient(
        ApiHttpClient(
            client=httpx.Client(
                transport=httpx.MockTransport(handler), base_url="https://api.lyrics.ovh/v1"
            )
        )
    )

    hit = client.get_lyrics(make_track(), "now")
    missed_track = make_track()
    object.__setattr__(missed_track, "name", "Missing")
    miss = client.get_lyrics(missed_track, "now")

    assert hit.match_status == "hit"
    assert hit.plain_lyrics == "fallback"
    assert miss.match_status == "miss"
