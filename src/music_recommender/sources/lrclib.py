from __future__ import annotations

from music_recommender.models import LyricsRecord, SpotifyTrack
from music_recommender.sources.http import ApiHttpClient

BASE_URL = "https://lrclib.net/api"


class LrcLibClient:
    def __init__(self, http: ApiHttpClient | None = None) -> None:
        self.http = http or ApiHttpClient(
            base_url=BASE_URL,
            headers={"User-Agent": "music-recommender/0.1 educational project"},
        )

    def close(self) -> None:
        self.http.close()

    def get_lyrics(self, track: SpotifyTrack, fetched_at: str) -> LyricsRecord:
        response = self.http.get(
            "/get",
            expected_statuses=(200, 404),
            params={
                "track_name": track.name,
                "artist_name": track.primary_artist_name or "",
                "album_name": track.album_name or "",
                "duration": round((track.duration_ms or 0) / 1000),
            },
        )
        if response.status_code == 404:
            return self._miss(track, fetched_at)

        payload = response.json()
        status = "instrumental" if payload.get("instrumental") else "hit"
        return LyricsRecord(
            spotify_track_id=track.id,
            track_name=track.name,
            artist_name=track.primary_artist_name or "",
            album_name=track.album_name,
            duration_ms=track.duration_ms,
            lyrics_source="lrclib",
            match_status=status,
            plain_lyrics=payload.get("plainLyrics"),
            synced_lyrics=payload.get("syncedLyrics"),
            lrclib_id=payload.get("id"),
            fetched_at=fetched_at,
            raw=payload,
        )

    @staticmethod
    def _miss(track: SpotifyTrack, fetched_at: str) -> LyricsRecord:
        return LyricsRecord(
            spotify_track_id=track.id,
            track_name=track.name,
            artist_name=track.primary_artist_name or "",
            album_name=track.album_name,
            duration_ms=track.duration_ms,
            lyrics_source="lrclib",
            match_status="miss",
            fetched_at=fetched_at,
        )
