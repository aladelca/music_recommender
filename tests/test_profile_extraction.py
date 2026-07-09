from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from music_recommender.pipeline.profile import (
    SpotifyProfileExtractionOptions,
    SpotifyProfileExtractor,
)
from music_recommender.storage.s3 import S3Storage


def test_spotify_profile_extractor_writes_medallion_profile_outputs(tmp_path: Path) -> None:
    storage = S3Storage(bucket=None, dry_run=True, local_root=tmp_path / "out")
    extractor = SpotifyProfileExtractor(spotify_client=FakeSpotifyProfileClient(), storage=storage)

    summary = extractor.run(
        SpotifyProfileExtractionOptions(
            run_id="profile-run",
            run_date="2026-07-09",
            file_format="parquet",
            top_limit=2,
            saved_limit=2,
            top_time_ranges=("short_term",),
            include_playlists=True,
            playlist_limit=1,
            playlist_track_limit=2,
            playlist_ids=("favorites",),
            include_recently_played=True,
            recently_played_limit=1,
            market="US",
        )
    )

    assert summary.counts["saved_tracks"] == 2
    assert summary.counts["top_tracks"] == 1
    assert summary.counts["top_artists"] == 1
    assert summary.counts["playlist_tracks"] == 1
    assert summary.counts["recent_tracks"] == 1
    assert (
        tmp_path / "out" / "silver/user_profile_track_signals/dt=2026-07-09/part-000.parquet"
    ).exists()
    assert (
        tmp_path / "out" / "gold/user_profile_track_interactions/dt=2026-07-09/part-000.parquet"
    ).exists()

    track_signals = read_parquet_rows(
        tmp_path / "out" / "silver/user_profile_track_signals/dt=2026-07-09/part-000.parquet"
    )
    assert [row["spotify_track_id"] for row in track_signals] == [
        "saved-1",
        "saved-2",
        "top-1",
        "playlist-1",
        "recent-1",
    ]
    assert {row["spotify_track_id"]: row["weight"] for row in track_signals}["saved-1"] == 1.0
    assert {row["spotify_track_id"]: row["weight"] for row in track_signals}["playlist-1"] == 0.6
    assert all("access_token" not in row for row in track_signals)
    assert all("refresh_token" not in row for row in track_signals)

    interactions = read_parquet_rows(
        tmp_path / "out" / "gold/user_profile_track_interactions/dt=2026-07-09/part-000.parquet"
    )
    assert {row["item_id"]: row["implicit_rating"] for row in interactions}["saved-1"] == 5.0
    assert {row["item_id"]: row["implicit_rating"] for row in interactions}["recent-1"] == 1.5

    metadata = json.loads((tmp_path / "out" / "metadata/runs/run_id=profile-run.json").read_text())
    assert metadata["counts"]["track_signals"] == 5
    assert "spotify_user_id:12175364859" in metadata["notes"]


def read_parquet_rows(path: Path) -> list[dict[str, Any]]:
    table = pq.read_table(path)  # type: ignore[no-untyped-call]
    return [dict(record) for record in table.to_pylist()]


class FakeSpotifyProfileClient:
    def get_current_user_profile(self) -> dict[str, Any]:
        return {
            "id": "12175364859",
            "account_id": "stable-account",
            "email": "hidden@example.com",
        }

    def iter_saved_tracks(
        self,
        *,
        limit_total: int,
        page_size: int = 50,
        market: str | None = None,
    ) -> list[dict[str, Any]]:
        assert limit_total == 2
        assert market == "US"
        return [
            {"track": spotify_track("saved-1", "Saved One", "Saved Artist")},
            {"track": spotify_track("saved-2", "Saved Two", "Saved Artist")},
        ]

    def iter_top_items(
        self,
        item_type: str,
        *,
        limit_total: int,
        time_range: str = "medium_term",
        page_size: int = 50,
    ) -> list[dict[str, Any]]:
        assert limit_total == 2
        assert time_range == "short_term"
        if item_type == "tracks":
            return [spotify_track("top-1", "Top One", "Top Artist")]
        if item_type == "artists":
            return [{"id": "artist-top", "name": "Top Artist"}]
        raise AssertionError(f"Unexpected item type: {item_type}")

    def iter_current_user_playlists(
        self,
        *,
        limit_total: int,
        page_size: int = 50,
    ) -> list[dict[str, Any]]:
        assert limit_total == 1
        return [{"id": "favorites", "name": "Favorites", "owner": {"id": "12175364859"}}]

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
        assert limit_total == 2
        assert market == "US"
        assert fields is not None
        return [{"track": spotify_track("playlist-1", "Playlist One", "Playlist Artist")}]

    def get_recently_played(
        self,
        *,
        limit: int = 20,
        before: int | None = None,
        after: int | None = None,
    ) -> dict[str, Any]:
        assert limit == 1
        return {"items": [{"track": spotify_track("recent-1", "Recent One", "Recent Artist")}]}


def spotify_track(track_id: str, name: str, artist_name: str) -> dict[str, Any]:
    return {
        "id": track_id,
        "name": name,
        "artists": [{"id": f"{artist_name}-id", "name": artist_name}],
        "duration_ms": 180000,
        "explicit": False,
        "popularity": 70,
        "external_ids": {"isrc": f"ISRC-{track_id}"},
        "external_urls": {"spotify": f"https://open.spotify.com/track/{track_id}"},
    }
