from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from music_recommender.api.app import create_app
from music_recommender.recommender.profile import JsonProfileCache, SpotifyProfileSyncService
from music_recommender.sources.http import ApiError


def test_profile_sync_and_status_routes() -> None:
    service = FakeApiService()
    client = TestClient(create_app(load_env=False, service=service))

    sync_response = client.post(
        "/profile/sync",
        json={
            "top_limit": 2,
            "saved_limit": 2,
            "top_time_ranges": ["short_term", "long_term"],
            "include_playlists": True,
            "playlist_limit": 2,
            "playlist_track_limit": 10,
            "playlist_ids": ["favorites"],
            "include_recently_played": True,
            "recently_played_limit": 1,
            "market": "US",
        },
    )
    status_response = client.get("/profile")

    assert sync_response.status_code == 200, sync_response.text
    assert sync_response.json()["profile"]["user_id"] == "12175364859"
    assert sync_response.json()["profile"]["liked_track_ids"] == ["top-1", "saved-1"]
    assert sync_response.json()["source_counts"]["saved_tracks"] == 1
    assert status_response.status_code == 200
    assert status_response.json()["present"] is True
    assert service.sync_request == {
        "top_limit": 2,
        "saved_limit": 2,
        "top_time_ranges": ["short_term", "long_term"],
        "include_playlists": True,
        "playlist_limit": 2,
        "playlist_track_limit": 10,
        "playlist_ids": ["favorites"],
        "include_recently_played": True,
        "recently_played_limit": 1,
        "market": "US",
    }


def test_profile_sync_service_normalizes_spotify_profile(tmp_path: Path) -> None:
    service = SpotifyProfileSyncService(
        spotify_client=FakeSpotifyProfileClient(),
        cache=JsonProfileCache(tmp_path / "profile.json"),
        required_user_id="12175364859",
    )

    snapshot = service.sync_profile(top_limit=2, saved_limit=2)
    cached = service.get_cached_profile()

    assert snapshot.profile.user_id == "12175364859"
    assert snapshot.profile.liked_track_ids == ("saved-1", "top-1")
    assert snapshot.profile.known_track_ids == ("saved-1", "top-1")
    assert snapshot.profile.liked_artist_names == ("Robyn", "Dua Lipa")
    assert cached is not None
    assert cached.profile == snapshot.profile


def test_profile_sync_service_enriches_profile_with_live_spotify_sources(
    tmp_path: Path,
) -> None:
    service = SpotifyProfileSyncService(
        spotify_client=RichFakeSpotifyProfileClient(),
        cache=JsonProfileCache(tmp_path / "profile.json"),
        required_user_id="12175364859",
    )

    snapshot = service.sync_profile(
        top_limit=3,
        saved_limit=3,
        top_time_ranges=("short_term", "long_term"),
        include_playlists=True,
        playlist_limit=2,
        playlist_track_limit=3,
        playlist_ids=("favorites",),
        include_recently_played=True,
        recently_played_limit=1,
        market="US",
    )
    cached = service.get_cached_profile()

    assert snapshot.spotify_user_id == "12175364859"
    assert snapshot.spotify_account_id == "stable-account"
    assert snapshot.source_counts == {
        "saved_tracks": 3,
        "top_tracks": 4,
        "top_artists": 2,
        "playlists": 1,
        "playlist_tracks": 2,
        "recent_tracks": 1,
    }
    assert snapshot.time_ranges == ("short_term", "long_term")
    assert snapshot.playlist_sources == (
        {
            "id": "favorites",
            "name": "Favorites",
            "owner_id": "12175364859",
            "tracks_read": 2,
        },
    )
    assert cached is not None
    assert cached.source_counts == snapshot.source_counts
    assert snapshot.profile.liked_track_ids == (
        "saved-1",
        "saved-2",
        "saved-3",
        "top-short",
        "top-long",
    )
    assert snapshot.profile.known_track_ids == (
        "saved-1",
        "saved-2",
        "saved-3",
        "top-short",
        "top-long",
        "playlist-boost",
        "recent-1",
    )
    assert snapshot.profile.liked_artist_names == (
        "Saved Artist",
        "Second Artist",
        "Third Artist",
        "Top Artist",
        "Long Artist",
    )
    assert snapshot.profile.track_affinity == {
        "saved-1": 1.0,
        "saved-2": 1.0,
        "saved-3": 1.0,
        "top-short": 0.9,
        "top-long": 0.7,
        "playlist-boost": 0.6,
        "recent-1": 0.3,
    }
    assert snapshot.profile.artist_affinity == {
        "Saved Artist": 0.9,
        "Second Artist": 0.9,
        "Third Artist": 0.9,
        "Top Artist": 0.9,
        "Long Artist": 0.7,
        "Playlist Artist": 0.6,
        "Recent Artist": 0.3,
    }
    assert snapshot.spotify_track_candidates == (
        {
            "id": "saved-1",
            "name": "saved-1",
            "artist_names": ["Saved Artist"],
            "primary_artist_name": "Saved Artist",
            "explicit": False,
            "popularity": None,
            "spotify_url": None,
        },
        {
            "id": "saved-2",
            "name": "saved-2",
            "artist_names": ["Second Artist"],
            "primary_artist_name": "Second Artist",
            "explicit": False,
            "popularity": None,
            "spotify_url": None,
        },
        {
            "id": "saved-3",
            "name": "saved-3",
            "artist_names": ["Third Artist"],
            "primary_artist_name": "Third Artist",
            "explicit": False,
            "popularity": None,
            "spotify_url": None,
        },
        {
            "id": "top-short",
            "name": "top-short",
            "artist_names": ["Top Artist"],
            "primary_artist_name": "Top Artist",
            "explicit": False,
            "popularity": None,
            "spotify_url": None,
        },
        {
            "id": "top-long",
            "name": "top-long",
            "artist_names": ["Long Artist"],
            "primary_artist_name": "Long Artist",
            "explicit": False,
            "popularity": None,
            "spotify_url": None,
        },
        {
            "id": "playlist-boost",
            "name": "playlist-boost",
            "artist_names": ["Playlist Artist"],
            "primary_artist_name": "Playlist Artist",
            "explicit": False,
            "popularity": None,
            "spotify_url": None,
        },
        {
            "id": "recent-1",
            "name": "recent-1",
            "artist_names": ["Recent Artist"],
            "primary_artist_name": "Recent Artist",
            "explicit": False,
            "popularity": None,
            "spotify_url": None,
        },
    )


def test_profile_sync_service_skips_inaccessible_playlists_and_continues(
    tmp_path: Path,
) -> None:
    service = SpotifyProfileSyncService(
        spotify_client=PartiallyInaccessiblePlaylistClient(),
        cache=JsonProfileCache(tmp_path / "profile.json"),
        required_user_id="12175364859",
    )

    snapshot = service.sync_profile(
        top_limit=1,
        saved_limit=1,
        include_playlists=True,
        playlist_limit=2,
        playlist_track_limit=2,
    )

    assert snapshot.source_counts["playlists"] == 2
    assert snapshot.source_counts["playlist_tracks"] == 1
    assert snapshot.missing_optional_scopes == ()
    assert snapshot.playlist_sources == (
        {
            "id": "blocked",
            "name": "Blocked Playlist",
            "owner_id": "other",
            "tracks_read": 0,
            "status": "skipped_inaccessible",
        },
        {
            "id": "readable",
            "name": "Readable Playlist",
            "owner_id": "12175364859",
            "tracks_read": 1,
        },
    )
    assert snapshot.profile.known_track_ids == ("saved-1", "top-1", "readable-track")
    assert snapshot.profile.liked_artist_names == ("Saved Artist", "Top Artist")


def test_profile_cache_loads_old_snapshot_shape(tmp_path: Path) -> None:
    path = tmp_path / "profile.json"
    path.write_text(
        json.dumps(
            {
                "profile": {
                    "user_id": "12175364859",
                    "liked_track_ids": ["saved-1"],
                    "known_track_ids": ["saved-1"],
                    "liked_artist_names": ["Saved Artist"],
                    "blocked_artist_names": [],
                },
                "source": "spotify",
                "synced_at": "2026-07-04T00:00:00Z",
            }
        )
    )

    snapshot = JsonProfileCache(path).load()

    assert snapshot is not None
    assert snapshot.profile.user_id == "12175364859"
    assert snapshot.source_counts == {}
    assert snapshot.playlist_sources == ()
    assert snapshot.time_ranges == ()
    assert snapshot.spotify_account_id is None


class FakeApiService:
    def __init__(self) -> None:
        self.sync_request: dict[str, Any] | None = None

    def sync_profile(self, request: Any) -> dict[str, Any]:
        self.sync_request = request.model_dump()
        return {
            "profile": {
                "user_id": "12175364859",
                "liked_track_ids": ["top-1", "saved-1"],
                "known_track_ids": ["top-1", "saved-1"],
                "liked_artist_names": ["Dua Lipa", "Robyn"],
                "blocked_artist_names": [],
            },
            "source": "spotify",
            "source_counts": {"saved_tracks": 1},
            "synced_at": "2026-07-03T23:00:00Z",
        }

    def get_profile_status(self) -> dict[str, Any]:
        return {
            "present": True,
            "profile": {
                "user_id": "12175364859",
                "liked_track_ids": ["top-1", "saved-1"],
                "known_track_ids": ["top-1", "saved-1"],
                "liked_artist_names": ["Dua Lipa", "Robyn"],
                "blocked_artist_names": [],
            },
            "synced_at": "2026-07-03T23:00:00Z",
        }


class FakeSpotifyProfileClient:
    def get_current_user_profile(self) -> dict[str, Any]:
        return {"id": "12175364859"}

    def get_top_items(
        self,
        item_type: str,
        *,
        limit: int = 20,
        offset: int = 0,
        time_range: str = "medium_term",
    ) -> dict[str, Any]:
        assert offset == 0
        assert time_range == "medium_term"
        if item_type == "tracks":
            assert limit == 2
            return {
                "items": [
                    {"id": "top-1", "artists": [{"name": "Dua Lipa"}]},
                    {"id": "saved-1", "artists": [{"name": "Dua Lipa"}]},
                ]
            }
        if item_type == "artists":
            assert limit == 2
            return {"items": [{"name": "Dua Lipa"}, {"name": "Robyn"}]}
        raise AssertionError(f"Unexpected top item type: {item_type}")

    def iter_top_items(
        self,
        item_type: str,
        *,
        limit_total: int,
        time_range: str = "medium_term",
        page_size: int = 50,
    ) -> list[dict[str, Any]]:
        payload = self.get_top_items(
            item_type,
            limit=limit_total,
            offset=0,
            time_range=time_range,
        )
        return list(payload["items"])

    def get_saved_tracks(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        market: str | None = None,
    ) -> dict[str, Any]:
        assert limit == 2
        assert offset == 0
        assert market is None
        return {"items": [{"track": {"id": "saved-1", "artists": [{"name": "Robyn"}]}}]}

    def iter_saved_tracks(
        self,
        *,
        limit_total: int,
        page_size: int = 50,
        market: str | None = None,
    ) -> list[dict[str, Any]]:
        payload = self.get_saved_tracks(limit=limit_total, offset=0, market=market)
        return list(payload["items"])

    def iter_current_user_playlists(
        self,
        *,
        limit_total: int,
        page_size: int = 50,
    ) -> list[dict[str, Any]]:
        return []

    def iter_playlist_items(
        self,
        playlist_id: str,
        *,
        limit_total: int,
        page_size: int = 50,
        market: str | None = None,
        fields: str | None = None,
    ) -> list[dict[str, Any]]:
        return []

    def get_recently_played(
        self,
        *,
        limit: int = 20,
        before: int | None = None,
        after: int | None = None,
    ) -> dict[str, Any]:
        return {"items": []}


class RichFakeSpotifyProfileClient:
    def get_current_user_profile(self) -> dict[str, Any]:
        return {"id": "12175364859", "account_id": "stable-account"}

    def iter_saved_tracks(
        self,
        *,
        limit_total: int,
        page_size: int = 50,
        market: str | None = None,
    ) -> list[dict[str, Any]]:
        assert limit_total == 3
        assert market == "US"
        return [
            {"track": {"id": "saved-1", "artists": [{"name": "Saved Artist"}]}},
            {"track": {"id": "saved-2", "artists": [{"name": "Second Artist"}]}},
            {"track": {"id": "saved-3", "artists": [{"name": "Third Artist"}]}},
        ]

    def iter_top_items(
        self,
        item_type: str,
        *,
        limit_total: int,
        time_range: str = "medium_term",
        page_size: int = 50,
    ) -> list[dict[str, Any]]:
        assert limit_total == 3
        if item_type == "tracks" and time_range == "short_term":
            return [
                {"id": "top-short", "artists": [{"name": "Top Artist"}]},
                {"id": "saved-1", "artists": [{"name": "Saved Artist"}]},
            ]
        if item_type == "tracks" and time_range == "long_term":
            return [
                {"id": "top-long", "artists": [{"name": "Long Artist"}]},
                {"id": "saved-2", "artists": [{"name": "Second Artist"}]},
            ]
        if item_type == "artists" and time_range == "short_term":
            return [{"name": "Top Artist"}]
        if item_type == "artists" and time_range == "long_term":
            return [{"name": "Long Artist"}]
        raise AssertionError(f"Unexpected top item request: {item_type} {time_range}")

    def iter_current_user_playlists(
        self,
        *,
        limit_total: int,
        page_size: int = 50,
    ) -> list[dict[str, Any]]:
        assert limit_total == 2
        return [
            {
                "id": "favorites",
                "name": "Favorites",
                "owner": {"id": "12175364859"},
            },
            {
                "id": "ignored",
                "name": "Old Playlist",
                "owner": {"id": "other"},
            },
        ]

    def iter_playlist_items(
        self,
        playlist_id: str,
        *,
        limit_total: int,
        page_size: int = 50,
        market: str | None = None,
        fields: str | None = None,
    ) -> list[dict[str, Any]]:
        assert playlist_id == "favorites"
        assert limit_total == 3
        assert market == "US"
        return [
            {"track": {"id": "playlist-boost", "artists": [{"name": "Playlist Artist"}]}},
            {"track": {"id": "saved-1", "artists": [{"name": "Saved Artist"}]}},
        ]

    def get_recently_played(
        self,
        *,
        limit: int = 20,
        before: int | None = None,
        after: int | None = None,
    ) -> dict[str, Any]:
        assert limit == 1
        return {"items": [{"track": {"id": "recent-1", "artists": [{"name": "Recent Artist"}]}}]}


class PartiallyInaccessiblePlaylistClient:
    def get_current_user_profile(self) -> dict[str, Any]:
        return {"id": "12175364859"}

    def iter_saved_tracks(
        self,
        *,
        limit_total: int,
        page_size: int = 50,
        market: str | None = None,
    ) -> list[dict[str, Any]]:
        return [{"track": {"id": "saved-1", "artists": [{"name": "Saved Artist"}]}}]

    def iter_top_items(
        self,
        item_type: str,
        *,
        limit_total: int,
        time_range: str = "medium_term",
        page_size: int = 50,
    ) -> list[dict[str, Any]]:
        if item_type == "tracks":
            return [{"id": "top-1", "artists": [{"name": "Top Artist"}]}]
        if item_type == "artists":
            return [{"name": "Top Artist"}]
        raise AssertionError(f"Unexpected item type: {item_type}")

    def iter_current_user_playlists(
        self,
        *,
        limit_total: int,
        page_size: int = 50,
    ) -> list[dict[str, Any]]:
        return [
            {"id": "blocked", "name": "Blocked Playlist", "owner": {"id": "other"}},
            {"id": "readable", "name": "Readable Playlist", "owner": {"id": "12175364859"}},
        ]

    def iter_playlist_items(
        self,
        playlist_id: str,
        *,
        limit_total: int,
        page_size: int = 50,
        market: str | None = None,
        fields: str | None = None,
    ) -> list[dict[str, Any]]:
        if playlist_id == "blocked":
            raise ApiError(status_code=403, url="/playlists/blocked/tracks", message="Forbidden")
        return [{"track": {"id": "readable-track", "artists": [{"name": "Playlist Artist"}]}}]

    def get_recently_played(
        self,
        *,
        limit: int = 20,
        before: int | None = None,
        after: int | None = None,
    ) -> dict[str, Any]:
        return {"items": []}
