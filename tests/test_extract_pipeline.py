from __future__ import annotations

from pathlib import Path

from music_recommender.models import (
    AudioFeaturesRecord,
    LyricsRecord,
    SpotifyAlbum,
    SpotifyArtist,
    SpotifyTrack,
)
from music_recommender.pipeline.extract import DataExtractor, ExtractionOptions
from music_recommender.storage.s3 import S3Storage


class FakeSpotify:
    def search_artist(self, name: str) -> SpotifyArtist | None:
        return SpotifyArtist(
            id=f"{name}-id",
            name=name,
            popularity=1,
            genres=[],
            spotify_url=None,
            seed_artist=name,
            raw={"id": f"{name}-id", "name": name},
        )

    def iter_artist_albums(self, artist: SpotifyArtist) -> list[SpotifyAlbum]:
        return [
            SpotifyAlbum(
                id=f"{artist.name}-album",
                name="Album",
                album_type="album",
                release_date="2024",
                total_tracks=3,
                artist_id=artist.id,
                seed_artist=artist.seed_artist,
                raw={},
            )
        ]

    def iter_album_track_ids(self, album_id: str) -> list[str]:
        return ["track-1", "track-2", "track-duplicate"]

    def get_track(self, track_id: str, *, seed_artist: str, spotify_artist_id: str) -> SpotifyTrack:
        is_duplicate = track_id == "track-duplicate"
        return SpotifyTrack(
            id=track_id,
            name="Song 1" if is_duplicate else track_id,
            duration_ms=100000,
            explicit=False,
            popularity=10,
            isrc="ISRC-1" if is_duplicate else track_id.upper(),
            album_id="album-1",
            album_name="Album",
            album_release_date="2024",
            artist_names=[seed_artist],
            primary_artist_name=seed_artist,
            spotify_url=None,
            seed_artist=seed_artist,
            spotify_artist_id=spotify_artist_id,
            raw={"id": track_id},
        )

    def get_audio_features(self, track_id: str, fetched_at: str) -> AudioFeaturesRecord:
        return AudioFeaturesRecord(
            spotify_track_id=track_id,
            enabled=True,
            status="hit",
            raw={"id": track_id, "danceability": 0.5},
            fetched_at=fetched_at,
        )


class FakeLrcLib:
    def get_lyrics(self, track: SpotifyTrack, fetched_at: str) -> LyricsRecord:
        if track.id == "track-2":
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
        return LyricsRecord(
            spotify_track_id=track.id,
            track_name=track.name,
            artist_name=track.primary_artist_name or "",
            album_name=track.album_name,
            duration_ms=track.duration_ms,
            lyrics_source="lrclib",
            match_status="hit",
            plain_lyrics="lyrics",
            fetched_at=fetched_at,
        )


class FakeLyricsOvh:
    def get_lyrics(self, track: SpotifyTrack, fetched_at: str) -> LyricsRecord:
        return LyricsRecord(
            spotify_track_id=track.id,
            track_name=track.name,
            artist_name=track.primary_artist_name or "",
            album_name=track.album_name,
            duration_ms=track.duration_ms,
            lyrics_source="lyrics_ovh",
            match_status="hit",
            plain_lyrics="fallback",
            fetched_at=fetched_at,
        )


class FakeReccoBeats:
    def get_audio_features(
        self,
        track_ids: list[str],
        fetched_at: str,
    ) -> list[AudioFeaturesRecord]:
        return [
            AudioFeaturesRecord(
                spotify_track_id=track_id,
                enabled=True,
                status="hit",
                source="reccobeats",
                raw={"id": track_id, "danceability": 0.7},
                fetched_at=fetched_at,
            )
            for track_id in track_ids
        ]


def test_pipeline_writes_local_outputs_and_counts(tmp_path: Path) -> None:
    seeds = tmp_path / "base.md"
    seeds.write_text("header\nArtist\n", encoding="utf-8")
    aliases = tmp_path / "aliases.yml"
    aliases.write_text("", encoding="utf-8")
    storage = S3Storage(bucket=None, dry_run=True, local_root=tmp_path / "out")
    extractor = DataExtractor(
        spotify=FakeSpotify(),
        lrclib=FakeLrcLib(),
        lyrics_ovh=FakeLyricsOvh(),
        storage=storage,
    )

    summary = extractor.run(
        ExtractionOptions(
            seeds_path=seeds,
            aliases_path=aliases,
            run_id="run-1",
            run_date="2026-05-21",
            max_tracks_per_artist=2,
            enable_audio_features=True,
            file_format="jsonl",
        )
    )

    assert summary.counts["seed_artists"] == 1
    assert summary.counts["tracks"] == 2
    assert summary.counts["lyrics_hits"] == 2
    assert summary.counts["audio_feature_records"] == 2
    assert summary.counts["audio_feature_hits"] == 2
    assert (tmp_path / "out" / "bronze/spotify/tracks/run_id=run-1/part-000.jsonl").exists()
    assert (tmp_path / "out" / "metadata/runs/run_id=run-1.json").exists()


def test_pipeline_uses_reccobeats_and_parquet_outputs(tmp_path: Path) -> None:
    seeds = tmp_path / "base.md"
    seeds.write_text("header\nArtist\n", encoding="utf-8")
    aliases = tmp_path / "aliases.yml"
    aliases.write_text("", encoding="utf-8")
    storage = S3Storage(bucket=None, dry_run=True, local_root=tmp_path / "out")
    extractor = DataExtractor(
        spotify=FakeSpotify(),
        lrclib=FakeLrcLib(),
        lyrics_ovh=FakeLyricsOvh(),
        storage=storage,
        reccobeats=FakeReccoBeats(),
    )

    summary = extractor.run(
        ExtractionOptions(
            seeds_path=seeds,
            aliases_path=aliases,
            run_id="run-1",
            run_date="2026-05-21",
            max_tracks_per_artist=2,
            audio_feature_source="reccobeats",
            file_format="parquet",
        )
    )

    assert summary.counts["audio_feature_hits"] == 2
    assert (
        tmp_path / "out" / "bronze/reccobeats/audio_features/run_id=run-1/part-000.parquet"
    ).exists()
    assert (tmp_path / "out" / "silver/lyrics_nlp/dt=2026-05-21/part-000.parquet").exists()
    assert (tmp_path / "out" / "metadata/runs/run_id=run-1.json").exists()
