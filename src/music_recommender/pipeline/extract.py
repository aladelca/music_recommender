from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol

from music_recommender.ingest.parse_base import normalize_lookup_key, parse_seed_artists
from music_recommender.models import (
    AudioFeaturesRecord,
    ExtractionSummary,
    JsonDict,
    LyricsNlpRecord,
    LyricsRecord,
    SeedArtist,
    SpotifyAlbum,
    SpotifyArtist,
    SpotifyTrack,
)
from music_recommender.storage.s3 import FileFormat, S3Storage, medallion_data_key, run_metadata_key

LOGGER = logging.getLogger(__name__)
AudioFeatureSourceName = Literal["none", "reccobeats", "spotify"]


class SpotifySource(Protocol):
    def search_artist(self, name: str) -> SpotifyArtist | None: ...

    def iter_artist_albums(self, artist: SpotifyArtist) -> list[SpotifyAlbum]: ...

    def iter_album_track_ids(self, album_id: str) -> list[str]: ...

    def get_track(
        self, track_id: str, *, seed_artist: str, spotify_artist_id: str
    ) -> SpotifyTrack: ...

    def get_audio_features(self, track_id: str, fetched_at: str) -> AudioFeaturesRecord: ...


class LyricsSource(Protocol):
    def get_lyrics(self, track: SpotifyTrack, fetched_at: str) -> LyricsRecord: ...


class BatchAudioFeaturesSource(Protocol):
    def get_audio_features(
        self,
        track_ids: list[str],
        fetched_at: str,
    ) -> list[AudioFeaturesRecord]: ...


class LyricsNlpSource(Protocol):
    def enrich(self, lyrics: LyricsRecord, run_id: str) -> LyricsNlpRecord: ...


@dataclass(frozen=True)
class ExtractionOptions:
    seeds_path: Path
    aliases_path: Path
    run_id: str
    run_date: str
    max_tracks_per_artist: int
    enable_audio_features: bool = False
    audio_feature_source: AudioFeatureSourceName = "none"
    file_format: FileFormat = "parquet"
    enable_lyrics_nlp: bool = False


class DataExtractor:
    def __init__(
        self,
        *,
        spotify: SpotifySource,
        lrclib: LyricsSource,
        lyrics_ovh: LyricsSource,
        storage: S3Storage,
        reccobeats: BatchAudioFeaturesSource | None = None,
        lyrics_nlp: LyricsNlpSource | None = None,
    ) -> None:
        self.spotify = spotify
        self.lrclib = lrclib
        self.lyrics_ovh = lyrics_ovh
        self.storage = storage
        self.reccobeats = reccobeats
        self.lyrics_nlp = lyrics_nlp

    def run(self, options: ExtractionOptions) -> ExtractionSummary:
        seeds = parse_seed_artists(options.seeds_path, options.aliases_path)
        summary = ExtractionSummary(run_id=options.run_id)
        summary.counts["seed_artists"] = len(seeds)
        LOGGER.info(
            "Parsed %s seed artists from %s",
            len(seeds),
            options.seeds_path,
        )

        artists: list[SpotifyArtist] = []
        albums: list[SpotifyAlbum] = []
        tracks: list[SpotifyTrack] = []
        lrclib_lyrics: list[LyricsRecord] = []
        lyrics_ovh_records: list[LyricsRecord] = []
        silver_lyrics: list[LyricsRecord] = []
        lyrics_nlp_records: list[LyricsNlpRecord] = []
        audio_features: list[AudioFeaturesRecord] = []

        fetched_at = current_timestamp()
        audio_feature_source = effective_audio_feature_source(options)

        for index, seed in enumerate(seeds, start=1):
            LOGGER.info("Resolving artist %s/%s: %s", index, len(seeds), seed.name)
            artist = self._resolve_artist(seed, summary)
            if artist is None:
                LOGGER.warning("Artist not resolved: %s", seed.name)
                continue
            artists.append(artist)
            LOGGER.info(
                "Resolved artist %s -> %s (%s)",
                seed.name,
                artist.name,
                artist.id,
            )

            artist_tracks, artist_albums = self._collect_artist_tracks(
                artist=artist,
                max_tracks=options.max_tracks_per_artist,
                summary=summary,
            )
            albums.extend(artist_albums)
            tracks.extend(artist_tracks)
            LOGGER.info(
                "Collected %s tracks from %s albums for %s",
                len(artist_tracks),
                len(artist_albums),
                artist.name,
            )

            for track in artist_tracks:
                LOGGER.debug("Fetching lyrics for %s - %s", track.primary_artist_name, track.name)
                lyrics = self.lrclib.get_lyrics(track, fetched_at)
                lrclib_lyrics.append(lyrics)
                selected_lyrics = lyrics
                if lyrics.match_status == "miss":
                    LOGGER.debug("LRCLIB miss for %s; trying lyrics.ovh", track.id)
                    fallback = self.lyrics_ovh.get_lyrics(track, fetched_at)
                    lyrics_ovh_records.append(fallback)
                    selected_lyrics = fallback if fallback.match_status != "miss" else lyrics
                LOGGER.debug(
                    "Lyrics status for %s: source=%s status=%s",
                    track.id,
                    selected_lyrics.lyrics_source,
                    selected_lyrics.match_status,
                )
                silver_lyrics.append(selected_lyrics)

                if options.enable_lyrics_nlp:
                    if self.lyrics_nlp is None:
                        summary.errors.append("lyrics_nlp_enabled_but_not_configured")
                        LOGGER.warning("Lyrics NLP enabled but no lyrics NLP source was configured")
                    else:
                        lyrics_nlp_records.append(
                            self.lyrics_nlp.enrich(selected_lyrics, options.run_id)
                        )

        audio_features = self._collect_audio_features(
            tracks=tracks,
            source=audio_feature_source,
            fetched_at=fetched_at,
            summary=summary,
        )

        self._write_outputs(
            options=options,
            summary=summary,
            fetched_at=fetched_at,
            seeds=seeds,
            artists=artists,
            albums=albums,
            tracks=tracks,
            lrclib_lyrics=lrclib_lyrics,
            lyrics_ovh_records=lyrics_ovh_records,
            silver_lyrics=silver_lyrics,
            lyrics_nlp_records=lyrics_nlp_records,
            audio_feature_source=audio_feature_source,
            audio_features=audio_features,
        )
        LOGGER.info("Extraction finished run_id=%s counts=%s", options.run_id, summary.counts)
        return summary

    def _resolve_artist(self, seed: SeedArtist, summary: ExtractionSummary) -> SpotifyArtist | None:
        try:
            artist = self.spotify.search_artist(seed.name)
        except Exception as error:  # noqa: BLE001
            summary.errors.append(f"artist_resolve_failed:{seed.name}:{error}")
            LOGGER.exception("Artist resolution failed for %s", seed.name)
            return None
        if artist is None:
            summary.errors.append(f"artist_not_found:{seed.name}")
            return None
        return artist

    def _collect_artist_tracks(
        self,
        *,
        artist: SpotifyArtist,
        max_tracks: int,
        summary: ExtractionSummary,
    ) -> tuple[list[SpotifyTrack], list[SpotifyAlbum]]:
        collected: list[SpotifyTrack] = []
        albums: list[SpotifyAlbum] = []
        seen_tracks: set[str] = set()
        seen_albums: set[str] = set()

        try:
            LOGGER.info("Fetching albums for %s", artist.name)
            candidate_albums = self.spotify.iter_artist_albums(artist)
        except Exception as error:  # noqa: BLE001
            summary.errors.append(f"album_fetch_failed:{artist.name}:{error}")
            LOGGER.exception("Album fetch failed for %s", artist.name)
            return collected, albums
        LOGGER.info("Found %s candidate albums for %s", len(candidate_albums), artist.name)

        for album in candidate_albums:
            if album.id in seen_albums:
                continue
            seen_albums.add(album.id)
            albums.append(album)
            LOGGER.debug("Fetching tracks for album %s (%s)", album.name, album.id)

            try:
                track_ids = self.spotify.iter_album_track_ids(album.id)
            except Exception as error:  # noqa: BLE001
                summary.errors.append(f"album_tracks_failed:{album.id}:{error}")
                LOGGER.exception("Album track fetch failed for %s", album.id)
                continue
            LOGGER.debug("Found %s track ids in album %s", len(track_ids), album.id)

            for track_id in track_ids:
                if len(collected) >= max_tracks:
                    LOGGER.info(
                        "Reached max track cap for %s: %s",
                        artist.name,
                        max_tracks,
                    )
                    return collected, albums
                try:
                    track = self.spotify.get_track(
                        track_id,
                        seed_artist=artist.seed_artist,
                        spotify_artist_id=artist.id,
                    )
                except Exception as error:  # noqa: BLE001
                    summary.errors.append(f"track_fetch_failed:{track_id}:{error}")
                    LOGGER.exception("Track fetch failed for %s", track_id)
                    continue

                dedupe_key = track_dedupe_key(track)
                if dedupe_key in seen_tracks:
                    LOGGER.debug("Skipping duplicate track %s (%s)", track.name, track.id)
                    continue
                seen_tracks.add(dedupe_key)
                collected.append(track)
                LOGGER.info(
                    "Collected track %s/%s for %s: %s",
                    len(collected),
                    max_tracks,
                    artist.name,
                    track.name,
                )

        return collected, albums

    def _collect_audio_features(
        self,
        *,
        tracks: list[SpotifyTrack],
        source: AudioFeatureSourceName,
        fetched_at: str,
        summary: ExtractionSummary,
    ) -> list[AudioFeaturesRecord]:
        if source == "none":
            LOGGER.info("Audio features disabled")
            return []

        track_ids = [track.id for track in tracks]
        if source == "reccobeats":
            if self.reccobeats is None:
                summary.errors.append("reccobeats_audio_features_not_configured")
                LOGGER.warning("ReccoBeats selected but no ReccoBeats client was configured")
                return []
            LOGGER.info("Fetching ReccoBeats audio features for %s tracks", len(track_ids))
            return self.reccobeats.get_audio_features(track_ids, fetched_at)

        LOGGER.info("Fetching Spotify audio features for %s tracks", len(track_ids))
        records: list[AudioFeaturesRecord] = []
        for track in tracks:
            LOGGER.debug("Fetching Spotify audio features for %s", track.id)
            feature_record = self.spotify.get_audio_features(track.id, fetched_at)
            if feature_record.status == "unavailable":
                summary.notes.append(
                    f"Spotify audio features unavailable for {track.id}: "
                    f"{feature_record.error_code}"
                )
                LOGGER.warning(
                    "Spotify audio features unavailable for %s: %s",
                    track.id,
                    feature_record.error_code,
                )
            records.append(feature_record)
        return records

    def _write_outputs(
        self,
        *,
        options: ExtractionOptions,
        summary: ExtractionSummary,
        fetched_at: str,
        seeds: list[SeedArtist],
        artists: list[SpotifyArtist],
        albums: list[SpotifyAlbum],
        tracks: list[SpotifyTrack],
        lrclib_lyrics: list[LyricsRecord],
        lyrics_ovh_records: list[LyricsRecord],
        silver_lyrics: list[LyricsRecord],
        lyrics_nlp_records: list[LyricsNlpRecord],
        audio_feature_source: AudioFeatureSourceName,
        audio_features: list[AudioFeaturesRecord],
    ) -> None:
        run_partition = f"run_id={options.run_id}"
        date_partition = f"dt={options.run_date}"
        audio_feature_dataset = (
            f"{audio_feature_source}/audio_features"
            if audio_feature_source != "none"
            else "audio_features"
        )
        audio_feature_hits = [record for record in audio_features if record.status == "hit"]

        writes = [
            self.storage.write_records(
                medallion_data_key("bronze", "seeds/artists", run_partition, options.file_format),
                [seed.to_dict() for seed in seeds],
                file_format=options.file_format,
            ),
            self.storage.write_records(
                medallion_data_key("bronze", "spotify/artists", run_partition, options.file_format),
                [artist.bronze_record(options.run_id, fetched_at) for artist in artists],
                file_format=options.file_format,
            ),
            self.storage.write_records(
                medallion_data_key("bronze", "spotify/albums", run_partition, options.file_format),
                [album.bronze_record(options.run_id, fetched_at) for album in albums],
                file_format=options.file_format,
            ),
            self.storage.write_records(
                medallion_data_key("bronze", "spotify/tracks", run_partition, options.file_format),
                [track.bronze_record(options.run_id, fetched_at) for track in tracks],
                file_format=options.file_format,
            ),
            self.storage.write_records(
                medallion_data_key(
                    "bronze", audio_feature_dataset, run_partition, options.file_format
                ),
                [record.to_dict() for record in audio_features],
                file_format=options.file_format,
            ),
            self.storage.write_records(
                medallion_data_key("bronze", "lyrics/lrclib", run_partition, options.file_format),
                [record.to_dict() for record in lrclib_lyrics],
                file_format=options.file_format,
            ),
            self.storage.write_records(
                medallion_data_key(
                    "bronze", "lyrics/lyrics_ovh", run_partition, options.file_format
                ),
                [record.to_dict() for record in lyrics_ovh_records],
                file_format=options.file_format,
            ),
            self.storage.write_records(
                medallion_data_key("silver", "artists", date_partition, options.file_format),
                [artist.silver_record(options.run_id) for artist in artists],
                file_format=options.file_format,
            ),
            self.storage.write_records(
                medallion_data_key("silver", "albums", date_partition, options.file_format),
                [album.silver_record(options.run_id) for album in albums],
                file_format=options.file_format,
            ),
            self.storage.write_records(
                medallion_data_key("silver", "tracks", date_partition, options.file_format),
                [track.silver_record(options.run_id) for track in tracks],
                file_format=options.file_format,
            ),
            self.storage.write_records(
                medallion_data_key("silver", "lyrics_clean", date_partition, options.file_format),
                [record.silver_record(options.run_id) for record in silver_lyrics],
                file_format=options.file_format,
            ),
            self.storage.write_records(
                medallion_data_key("silver", "audio_features", date_partition, options.file_format),
                [record.silver_record(options.run_id) for record in audio_feature_hits],
                file_format=options.file_format,
            ),
            self.storage.write_records(
                medallion_data_key("silver", "lyrics_nlp", date_partition, options.file_format),
                [record.to_dict() for record in lyrics_nlp_records],
                file_format=options.file_format,
            ),
        ]

        summary.outputs.extend(write.uri for write in writes)
        for write in writes:
            LOGGER.info("Wrote %s records to %s", write.count, write.uri)
        summary.counts.update(
            {
                "resolved_artists": len(artists),
                "albums": len(albums),
                "tracks": len(tracks),
                "lrclib_records": len(lrclib_lyrics),
                "lyrics_ovh_records": len(lyrics_ovh_records),
                "lyrics_hits": sum(1 for record in silver_lyrics if record.match_status != "miss"),
                "lyrics_misses": sum(
                    1 for record in silver_lyrics if record.match_status == "miss"
                ),
                "audio_feature_records": len(audio_features),
                "audio_feature_hits": len(audio_feature_hits),
                "audio_feature_misses": sum(
                    1 for record in audio_features if record.status == "miss"
                ),
                "lyrics_nlp_records": len(lyrics_nlp_records),
            }
        )

        metadata: JsonDict = summary.to_dict()
        metadata_write = self.storage.write_json(run_metadata_key(options.run_id), metadata)
        summary.outputs.append(metadata_write.uri)
        LOGGER.info("Wrote run metadata to %s", metadata_write.uri)


def track_dedupe_key(track: SpotifyTrack) -> str:
    if track.isrc:
        return f"isrc:{track.isrc.upper()}"
    normalized_title = normalize_lookup_key(strip_version_suffix(track.name))
    normalized_artist = normalize_lookup_key(track.primary_artist_name or "")
    duration_bucket = round((track.duration_ms or 0) / 1000)
    return f"fallback:{normalized_title}:{normalized_artist}:{duration_bucket}"


def strip_version_suffix(value: str) -> str:
    return re.sub(r"\s*-\s*(remaster(?:ed)?|live|edit|radio edit).*$", "", value, flags=re.I)


def current_timestamp() -> str:
    return datetime.now(UTC).isoformat()


def effective_audio_feature_source(options: ExtractionOptions) -> AudioFeatureSourceName:
    if options.enable_audio_features and options.audio_feature_source == "none":
        return "spotify"
    return options.audio_feature_source
