from __future__ import annotations

import base64
import time
from typing import Any

from music_recommender.ingest.parse_base import normalize_lookup_key
from music_recommender.models import (
    AudioFeaturesRecord,
    JsonDict,
    SpotifyAlbum,
    SpotifyArtist,
    SpotifyTrack,
)
from music_recommender.sources.http import ApiError, ApiHttpClient

AUTH_BASE_URL = "https://accounts.spotify.com"
API_BASE_URL = "https://api.spotify.com/v1"


class SpotifyClient:
    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        market: str = "US",
        auth_http: ApiHttpClient | None = None,
        api_http: ApiHttpClient | None = None,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.market = market
        self.auth_http = auth_http or ApiHttpClient(base_url=AUTH_BASE_URL)
        self.api_http = api_http or ApiHttpClient(base_url=API_BASE_URL)
        self._access_token: str | None = None
        self._expires_at = 0.0

    def close(self) -> None:
        self.auth_http.close()
        self.api_http.close()

    def get_access_token(self) -> str:
        if self._access_token and time.time() < self._expires_at - 30:
            return self._access_token

        credentials = f"{self.client_id}:{self.client_secret}".encode()
        encoded = base64.b64encode(credentials).decode("ascii")
        response = self.auth_http.post(
            "/api/token",
            headers={
                "Authorization": f"Basic {encoded}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={"grant_type": "client_credentials"},
        )
        payload = response.json()
        token = str(payload["access_token"])
        expires_in = int(payload.get("expires_in", 3600))
        self._access_token = token
        self._expires_at = time.time() + expires_in
        return token

    def search_artist(self, name: str) -> SpotifyArtist | None:
        payload = self._get(
            "/search",
            params={"q": name, "type": "artist", "market": self.market, "limit": 10},
        )
        artists = payload.get("artists", {}).get("items", [])
        if not artists:
            return None

        normalized_name = normalize_lookup_key(name)
        exact_matches = [
            artist
            for artist in artists
            if normalize_lookup_key(str(artist.get("name", ""))) == normalized_name
        ]
        candidate = max(
            exact_matches or artists,
            key=lambda artist: int(artist.get("popularity") or 0),
        )
        return SpotifyArtist.from_raw(candidate, seed_artist=name)

    def iter_artist_albums(self, artist: SpotifyArtist) -> list[SpotifyAlbum]:
        albums: list[SpotifyAlbum] = []
        seen: set[str] = set()
        offset = 0
        limit = 10
        while True:
            payload = self._get(
                f"/artists/{artist.id}/albums",
                params={
                    "include_groups": "album,single",
                    "market": self.market,
                    "limit": limit,
                    "offset": offset,
                },
            )
            items = payload.get("items", [])
            for item in items:
                album_id = str(item.get("id"))
                if album_id in seen:
                    continue
                seen.add(album_id)
                albums.append(
                    SpotifyAlbum.from_raw(item, artist_id=artist.id, seed_artist=artist.seed_artist)
                )

            if not items or not payload.get("next"):
                break
            offset += limit
        return albums

    def iter_album_track_ids(self, album_id: str) -> list[str]:
        track_ids: list[str] = []
        offset = 0
        limit = 50
        while True:
            payload = self._get(
                f"/albums/{album_id}/tracks",
                params={"market": self.market, "limit": limit, "offset": offset},
            )
            items = payload.get("items", [])
            for item in items:
                track_id = item.get("id")
                if track_id:
                    track_ids.append(str(track_id))

            if not items or not payload.get("next"):
                break
            offset += limit
        return track_ids

    def get_track(self, track_id: str, *, seed_artist: str, spotify_artist_id: str) -> SpotifyTrack:
        payload = self._get(f"/tracks/{track_id}", params={"market": self.market})
        return SpotifyTrack.from_raw(
            payload, seed_artist=seed_artist, spotify_artist_id=spotify_artist_id
        )

    def get_audio_features(self, track_id: str, fetched_at: str) -> AudioFeaturesRecord:
        try:
            payload = self._get(f"/audio-features/{track_id}")
        except ApiError as error:
            if error.status_code in {403, 404}:
                return AudioFeaturesRecord(
                    spotify_track_id=track_id,
                    enabled=True,
                    status="unavailable",
                    error_code=error.status_code,
                    fetched_at=fetched_at,
                )
            raise
        return AudioFeaturesRecord(
            spotify_track_id=track_id,
            enabled=True,
            status="hit",
            raw=payload,
            fetched_at=fetched_at,
        )

    def _get(self, path: str, **kwargs: Any) -> JsonDict:
        response = self.api_http.get(
            path,
            headers={"Authorization": f"Bearer {self.get_access_token()}"},
            **kwargs,
        )
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError(f"Spotify response must be an object: {path}")
        return payload
