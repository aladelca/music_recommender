# Data Extraction

## Product Runtime (Authoritative)

The Outside the Loop product does not extract, upload, or read catalog datasets from local disk or
S3. It does not deploy CSV or Parquet data. Runtime data moves through bounded HTTPS API calls and
normalized Supabase Postgres records only:

1. MusicBrainz search resolves explicit user-selected artist or recording MBIDs.
2. ListenBrainz Core artist/tag radio expands those seeds into recording MBIDs.
3. ListenBrainz recording metadata supplies title, artist credit, ISRC, release, and tag facts.
4. The backend ranks independent candidates before any Spotify lookup.
5. Spotify track search maps only the ranked MBIDs needed for attributed display and playlist
   export. Spotify popularity and user profile/listening data are not ranking inputs.

Positive MusicBrainz and ListenBrainz responses, negative lookups, canonical entities, candidate
edges, and Spotify mappings are stored in Supabase with explicit expiries. The deployment package
gate rejects `.csv` and `.parquet` files. `scripts/audit_beta_sources.py` queries Supabase directly
and emits aggregate coverage to stdout; it creates no data file.

## Legacy Offline Pipeline

The sections below describe the pre-product experimentation pipeline. That code is retained for
reproducibility and rollback only. Its local/S3 medallion datasets, Spotify profile extraction,
ListenBrainz dumps, ReccoBeats, and lyric features are not reachable from product routes or product
Lambda functions and must not be included in product deployment artifacts.

## Sources

- Spotify: catalog metadata, artist resolution, albums, tracks, popularity, URLs, and ISRCs.
- ReccoBeats: default source for audio features such as danceability, energy, tempo, and valence.
- LRCLIB: primary lyrics source for plain and synced lyrics.
- lyrics.ovh: fallback plain lyrics source when LRCLIB misses.
- fastText: optional lyrics language detection.
- CardiffNLP XLM-R multilingual sentiment: optional lyrics sentiment feature.
- ListenBrainz public dumps: recommended source for user-track network data.

No paid APIs are used. Lyric scraping is intentionally out of scope for this phase.

## Medallion Layout

```text
s3://<bucket>/
  bronze/
    spotify/artists/run_id=<run_id>/part-000.parquet
    spotify/albums/run_id=<run_id>/part-000.parquet
    spotify/tracks/run_id=<run_id>/part-000.parquet
    reccobeats/audio_features/run_id=<run_id>/part-000.parquet
    lyrics/lrclib/run_id=<run_id>/part-000.parquet
    lyrics/lyrics_ovh/run_id=<run_id>/part-000.parquet
    spotify/user_profile/run_id=<run_id>/part-000.parquet
    spotify/saved_tracks/run_id=<run_id>/part-000.parquet
    spotify/top_tracks/run_id=<run_id>/part-000.parquet
    spotify/top_artists/run_id=<run_id>/part-000.parquet
    spotify/playlists/run_id=<run_id>/part-000.parquet
    spotify/playlist_tracks/run_id=<run_id>/part-000.parquet
    network/listenbrainz/run_id=<run_id>/part-000.parquet
  silver/
    artists/dt=<yyyy-mm-dd>/part-000.parquet
    albums/dt=<yyyy-mm-dd>/part-000.parquet
    tracks/dt=<yyyy-mm-dd>/part-000.parquet
    audio_features/dt=<yyyy-mm-dd>/part-000.parquet
    lyrics_clean/dt=<yyyy-mm-dd>/part-000.parquet
    lyrics_nlp/dt=<yyyy-mm-dd>/part-000.parquet
    user_profile_track_signals/dt=<yyyy-mm-dd>/part-000.parquet
    user_profile_artist_signals/dt=<yyyy-mm-dd>/part-000.parquet
    network/listens/dt=<yyyy-mm-dd>/part-000.parquet
  gold/
    user_track_interactions/dt=<yyyy-mm-dd>/part-000.parquet
    user_profile_track_interactions/dt=<yyyy-mm-dd>/part-000.parquet
  metadata/
    runs/run_id=<run_id>.json
```

JSONL remains available with `--file-format jsonl`, but Parquet is the default for data
tables. Run metadata intentionally remains JSON at `metadata/runs/run_id=<run_id>.json`.

## Limits

- Each seed artist is capped at 150 deduplicated songs.
- ReccoBeats audio features can miss some Spotify tracks. Misses are recorded and extraction continues.
- Spotify audio features are optional fallback only. If Spotify returns an access error, extraction continues.
- Tracks are deduplicated by ISRC when available, otherwise by normalized title, primary artist, and duration.
- Use `--output local` to save data locally under `data/local/<run_id>/`.
- Use `--output s3` to upload the same medallion layout to S3.
- Use `--log-level DEBUG` to show detailed progress while a run is active.
- Recommender S3 reads support promoted `silver`/`gold` datasets partitioned by
  `dt=<yyyy-mm-dd>` and filter rows by `source_run_id`. Legacy `run_id=<run_id>` S3 partitions are
  still accepted as a fallback.
- Authenticated Spotify profile extraction writes only whitelisted profile, track, artist, and
  playlist fields. OAuth tokens and email are intentionally excluded.

## Source Notes

Spotify metadata is used for data collection and catalog resolution. Future recommender
training should prioritize lyrics and open/non-Spotify signals to avoid relying on restricted
Spotify content for ML training.

Spotify does not expose public user-like or user-listening network data. For collaborative
filtering, use ListenBrainz public dumps first. If the app later has real users, collect
Spotify user-library or listening data only through OAuth consent and user-scoped permissions.
