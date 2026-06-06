from __future__ import annotations

from urllib.parse import quote

from music_recommender.models import LyricsRecord, SpotifyTrack
from music_recommender.sources.http import ApiHttpClient

BASE_URL = "https://api.lyrics.ovh/v1"


class LyricsOvhClient:
    def __init__(self, http: ApiHttpClient | None = None) -> None:
        self.http = http or ApiHttpClient(base_url=BASE_URL)

    def close(self) -> None:
        self.http.close()

    def get_lyrics(self, track: SpotifyTrack, fetched_at: str) -> LyricsRecord:
        artist_name = track.primary_artist_name or ""
        path = f"/{quote(artist_name, safe='')}/{quote(track.name, safe='')}"
        response = self.http.get(path, expected_statuses=(200, 404))
        if response.status_code == 404:
            return LyricsRecord(
                spotify_track_id=track.id,
                track_name=track.name,
                artist_name=artist_name,
                album_name=track.album_name,
                duration_ms=track.duration_ms,
                lyrics_source="lyrics_ovh",
                match_status="miss",
                fetched_at=fetched_at,
            )

        payload = response.json()
        lyrics = payload.get("lyrics")
        return LyricsRecord(
            spotify_track_id=track.id,
            track_name=track.name,
            artist_name=artist_name,
            album_name=track.album_name,
            duration_ms=track.duration_ms,
            lyrics_source="lyrics_ovh",
            match_status="hit" if lyrics else "miss",
            plain_lyrics=lyrics,
            fetched_at=fetched_at,
            raw=payload,
        )
