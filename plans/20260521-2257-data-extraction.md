# Music Data Extraction Pipeline

## Goal

- Build a local Python extraction pipeline that reads artist seeds from `docs/base.md`, resolves catalog data from Spotify, fetches lyrics from free sources, and writes raw/curated outputs into S3 using a medallion-style layout.
- Limit extraction to `150` songs or fewer per seed artist.
- Keep implementation local, with AWS CLI used to bootstrap S3 storage and Python used for API extraction/upload.

## Request Snapshot

- User request: "Plan the data extraction part for a music recommender. Use Spotify credentials from `.env`, include up to 150 songs or less, focus first on getting the data, use LRCLIB as primary lyrics source, use S3 buckets with medallion schema in AWS via CLI, no paid sources, and consider Spotify audio features if available."
- Owner or issue: `None`
- Plan file: `plans/20260521-2257-data-extraction.md`

## Current State

- Repository is a minimal skeleton with only:
  - `docs/base.md`: seed singers/bands entered as free-form text.
  - `.env`: ignored by Git and contains Spotify app credentials using `SPOTIFY_APP_CLIENT_ID` and `SPOTIFY_APP_CLIENT_SECRET`.
  - `.gitignore`: currently ignores `.env`.
- No Python package, `pyproject.toml`, source modules, tests, or README exist yet.
- Local tooling detected:
  - Python: `Python 3.12.0`
  - `uv`: available at `/Users/adrianalarcon/.local/bin/uv`
  - `ruff`: available
  - `mypy`: available
  - `aws`: available
- AWS CLI credentials respond to `aws sts get-caller-identity`; default region is `us-east-1`.
- `docs/base.md` includes duplicates, mixed casing, punctuation, labels like `singer:`/`band:`, and typos such as `kaliuchis`, `Edsheeran`, and `red hot chilli pepers`.

## Findings

- Spotify is suitable for catalog metadata resolution:
  - `GET /search` can resolve artist names and tracks.
  - `GET /artists/{id}/albums` can list album/single releases.
  - `GET /albums/{id}/tracks` can list track items.
  - `GET /tracks/{id}` can fetch individual track metadata such as ISRC, duration, explicit flag, popularity, URLs, album, and artist credits.
- Spotify `GET /audio-features/{id}` is documented as deprecated and may be restricted for newer/development-mode apps. Implement it as optional extraction: call it only when enabled, persist results when returned, and continue if Spotify returns `403`, `404`, or another access-related failure.
- LRCLIB is the primary lyrics source because it is free, supports plain and synced lyrics, and can match by track, artist, album, and duration.
- `lyrics.ovh` is a reasonable free fallback for plain lyrics, but coverage and reliability are weaker.
- Genius should not be the first lyrics source for this phase. It can be used only as metadata/URL fallback later, because the official API is not a clean full-lyrics API.
- MusicBrainz, Last.fm, ListenBrainz, and AcousticBrainz are useful future enrichment sources, but they are out of scope for the first extraction implementation unless needed for matching fallback.

## Scope

### In scope

- Create Python project structure and tooling config.
- Parse and normalize `docs/base.md` into unique seed artists.
- Add an alias/normalization file for known typos and casing issues.
- Authenticate to Spotify using client credentials from `.env`.
- Resolve each seed artist to a Spotify artist candidate.
- Extract up to `150` tracks per artist by walking albums and singles.
- Fetch track metadata one track at a time to keep compatibility with newer Spotify endpoint restrictions.
- Optionally attempt Spotify audio features when enabled; gracefully skip when unavailable.
- Fetch lyrics from LRCLIB first, then `lyrics.ovh` fallback.
- Write JSONL records to S3 under bronze prefixes.
- Produce basic silver cleaned outputs locally in-process and upload to S3 under silver prefixes.
- Provide AWS CLI bootstrap script for S3 medallion bucket/prefix setup.
- Add unit tests and mocked integration-style tests for parsing, API clients, rate-limit behavior, and S3 key generation.
- Add validation commands for `ruff format`, `ruff check`, `mypy`, and `pytest`.

### Out of scope

- Building the recommender model.
- Training ML/AI models on Spotify content.
- UI or API server.
- Paid APIs.
- Scraping paid or copyrighted lyric sources.
- Glue Data Catalog, Athena DDL, Lake Formation, or crawler setup in this phase.
- Full data warehouse transformations beyond basic silver cleaned outputs.
- Deployment to Lambda, ECS, Glue jobs, or scheduled cloud compute.

## File Plan

| Path | Action | Details |
| --- | --- | --- |
| `pyproject.toml` | create | Define package metadata, Python `>=3.12`, dependencies, dev dependencies, `ruff`, `mypy`, and `pytest` config. |
| `.gitignore` | modify | Keep `.env`; add `.venv/`, `data/`, `.pytest_cache/`, `.ruff_cache/`, `.mypy_cache/`, and local run artifacts. |
| `.env.example` | create | Document non-secret env vars: `SPOTIFY_APP_CLIENT_ID`, `SPOTIFY_APP_CLIENT_SECRET`, `AWS_REGION`, `MUSIC_RECOMMENDER_BUCKET`, `SPOTIFY_MARKET`, `MAX_TRACKS_PER_ARTIST`, `ENABLE_SPOTIFY_AUDIO_FEATURES`. |
| `README.md` | create | Add setup, AWS bootstrap, extraction, test, and validation commands. |
| `docs/data-extraction.md` | create | Explain sources, medallion layout, data contracts, source limitations, and fallback order. |
| `config/artist_aliases.yml` | create | Map known dirty seed names to canonical artist names, for example `kaliuchis` -> `Kali Uchis`, `Edsheeran` -> `Ed Sheeran`, `red hot chilli pepers` -> `Red Hot Chili Peppers`. |
| `scripts/bootstrap_s3_medallion.sh` | create | Use AWS CLI to create or verify one S3 bucket and initialize medallion prefixes with placeholder objects. |
| `src/music_recommender/__init__.py` | create | Package marker. |
| `src/music_recommender/config.py` | create | Load `.env`, validate required settings, expose typed settings. Support `SPOTIFY_APP_*` and optionally standard aliases `SPOTIFY_CLIENT_ID`/`SPOTIFY_CLIENT_SECRET`. |
| `src/music_recommender/models.py` | create | Define dataclasses or typed dicts for `SeedArtist`, `SpotifyArtist`, `SpotifyAlbum`, `SpotifyTrack`, `SpotifyAudioFeatures`, `LyricsRecord`, and extraction run metadata. |
| `src/music_recommender/ingest/parse_base.py` | create | Parse `docs/base.md`, split comma-separated entries, strip labels/quotes/punctuation, apply aliases, dedupe canonical artists. |
| `src/music_recommender/sources/http.py` | create | Shared HTTP client helpers: timeout, retry/backoff, `429` handling, JSON parsing, safe error objects. |
| `src/music_recommender/sources/spotify.py` | create | Implement client credentials auth, artist search, artist albums, album tracks, track metadata, optional audio features. |
| `src/music_recommender/sources/lrclib.py` | create | Implement LRCLIB lyrics lookup by track/artist/album/duration, return plain/synced lyrics and match metadata. |
| `src/music_recommender/sources/lyrics_ovh.py` | create | Implement fallback plain lyric lookup by artist/title. |
| `src/music_recommender/storage/s3.py` | create | Implement S3 JSONL upload, medallion key builder, run metadata upload, and local writer option for tests and local runs. |
| `src/music_recommender/pipeline/extract.py` | create | Orchestrate full extraction: parse seeds, resolve artists, collect tracks, lyrics, optional audio features, write S3 records. |
| `src/music_recommender/cli.py` | create | CLI entry point with args like `--seeds`, `--output local/s3`, `--bucket`, `--max-tracks-per-artist`, `--market`, `--run-date`, `--dry-run`, `--enable-audio-features`. |
| `tests/test_parse_base.py` | create | Unit tests for seed parsing, quote handling, labels, comma split, aliases, casing, and dedupe. |
| `tests/test_spotify_client.py` | create | Mock HTTP tests for token auth, pagination, track metadata fetch, audio feature fallback on `403/404`, and `429` retry behavior. |
| `tests/test_lyrics_clients.py` | create | Mock LRCLIB and lyrics.ovh successful/missing lyric cases and fallback selection. |
| `tests/test_s3_storage.py` | create | Unit tests for bucket/prefix/key generation, JSONL serialization, dry-run writes, and run metadata. |
| `tests/test_extract_pipeline.py` | create | Mock end-to-end extraction with small seed set and assert bronze/silver outputs are produced with max-track cap enforced. |

## Data and Contract Changes

- Environment variables:
  - `SPOTIFY_APP_CLIENT_ID`: required.
  - `SPOTIFY_APP_CLIENT_SECRET`: required.
  - `MUSIC_RECOMMENDER_BUCKET`: required for S3 upload mode.
  - `AWS_REGION`: default from `aws configure get region`, currently `us-east-1`.
  - `SPOTIFY_MARKET`: default `US`.
  - `MAX_TRACKS_PER_ARTIST`: default `150`.
  - `ENABLE_SPOTIFY_AUDIO_FEATURES`: default `false`, can be set to `true`.
- S3 medallion layout:
  - `bronze/spotify/artists/run_id=<run_id>/part-000.jsonl`
  - `bronze/spotify/albums/run_id=<run_id>/part-000.jsonl`
  - `bronze/spotify/tracks/run_id=<run_id>/part-000.jsonl`
  - `bronze/spotify/audio_features/run_id=<run_id>/part-000.jsonl`
  - `bronze/lyrics/lrclib/run_id=<run_id>/part-000.jsonl`
  - `bronze/lyrics/lyrics_ovh/run_id=<run_id>/part-000.jsonl`
  - `silver/artists/dt=<yyyy-mm-dd>/part-000.jsonl`
  - `silver/albums/dt=<yyyy-mm-dd>/part-000.jsonl`
  - `silver/tracks/dt=<yyyy-mm-dd>/part-000.jsonl`
  - `silver/lyrics_clean/dt=<yyyy-mm-dd>/part-000.jsonl`
  - `metadata/runs/run_id=<run_id>.json`
- Bronze Spotify track record fields:
  - `run_id`, `source`, `seed_artist`, `spotify_artist_id`, `spotify_track_id`, `raw`, `fetched_at`.
- Silver track record fields:
  - `spotify_track_id`, `isrc`, `track_name`, `artist_names`, `primary_artist_name`, `album_name`, `release_date`, `duration_ms`, `explicit`, `popularity`, `spotify_url`, `seed_artist`, `source_run_id`.
- Lyrics record fields:
  - `spotify_track_id`, `track_name`, `artist_name`, `album_name`, `duration_ms`, `lyrics_source`, `match_status`, `plain_lyrics`, `synced_lyrics`, `lrclib_id`, `fetched_at`.
- Audio features record fields:
  - `spotify_track_id`, `enabled`, `status`, `raw`, `error_code`, `fetched_at`.
  - If audio features are unavailable, write a run-level note and skip per-track records unless partial successes exist.

## Implementation Steps

1. Add Python project scaffolding in `pyproject.toml` with:
   - Runtime dependencies: `httpx`, `python-dotenv`, `boto3`, `PyYAML`.
   - Dev dependencies: `pytest`, `respx` or `pytest-httpx`, `ruff`, `mypy`, `boto3-stubs[s3]` if practical.
   - Console script: `music-recommender-extract = "music_recommender.cli:main"`.
2. Expand `.gitignore` and create `.env.example` so secrets remain local and expected settings are clear.
3. Create `config/artist_aliases.yml` with known corrections from `docs/base.md`.
4. Implement `parse_base.py`:
   - Skip the header line.
   - Treat commas as separators.
   - Strip wrapping quotes.
   - Remove `singer:` and `band:` labels.
   - Remove trailing periods.
   - Collapse whitespace.
   - Apply alias map.
   - Dedupe case-insensitively while preserving canonical names.
5. Implement `config.py`:
   - Load `.env`.
   - Read Spotify credentials from `SPOTIFY_APP_CLIENT_ID` and `SPOTIFY_APP_CLIENT_SECRET`.
   - Also support `SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET` as future-compatible aliases.
   - Validate S3 bucket only when running with `--output s3`.
6. Implement shared HTTP behavior:
   - 10 to 20 second timeout.
   - Exponential backoff for transient `5xx` and `429`.
   - Respect Spotify `Retry-After` when present.
   - Add source-specific user agent where appropriate.
7. Implement Spotify source:
   - `get_access_token()`: client credentials auth.
   - `search_artist(name)`: choose best candidate by exact/normalized name first, fallback to highest popularity.
   - `iter_artist_albums(artist_id)`: page through album/single releases using current max page size.
   - `iter_album_tracks(album_id)`: page through tracks.
   - `get_track(track_id)`: fetch full track metadata individually.
   - `get_audio_features(track_id)`: optional, catches access errors and returns structured unavailable status.
8. Implement dedupe and track cap:
   - Dedupe tracks by ISRC when available, else normalized `(track_name, primary_artist, duration_ms)`.
   - Stop each seed artist at `max_tracks_per_artist <= 150`.
   - Prefer original album/single versions over compilations and duplicates where metadata allows.
9. Implement lyrics sources:
   - LRCLIB lookup using `track_name`, `artist_name`, `album_name`, and duration in seconds.
   - If LRCLIB misses, call lyrics.ovh by `artist/title`.
   - Do not scrape lyric websites in this phase.
10. Implement `storage/s3.py`:
    - Convert records to JSONL.
    - Upload to `s3://<bucket>/<prefix>`.
    - Support local writes under `data/local/<run_id>/`.
    - Upload `metadata/runs/run_id=<run_id>.json` with counts, errors, and source availability.
11. Implement CLI pipeline:
    - Default command reads `docs/base.md`.
    - Default max cap is `150`.
    - Default `--enable-audio-features` follows env var and is off unless explicitly enabled.
    - Support `--output local` for local JSONL output and `--output s3` for S3 upload.
    - Print a concise run summary: seed artists, resolved artists, tracks collected, lyrics hits/misses, S3 paths.
12. Create `scripts/bootstrap_s3_medallion.sh`:
    - Resolve account/region using AWS CLI.
    - Default bucket name: `music-recommender-${ACCOUNT}-${REGION}` unless `MUSIC_RECOMMENDER_BUCKET` is set.
    - Create bucket if missing.
    - Add placeholder objects for `bronze/`, `silver/`, `gold/`, and `metadata/`.
    - Print `export MUSIC_RECOMMENDER_BUCKET=...`.
13. Add docs:
    - `README.md` with setup, bootstrap, local run, S3 run, and validation.
    - `docs/data-extraction.md` with source priority, limitations, schemas, and S3 layout.

## Tests

- Unit: `tests/test_parse_base.py`
  - Covers header skip, comma separation, quoted multi-line singer/band block, labels, aliases, punctuation, duplicates, and lowercase input.
- Unit: `tests/test_spotify_client.py`
  - Mocks token auth, artist search selection, album pagination, album track pagination, track metadata fetch, audio features success, audio features `403/404` skip, and `429` retry behavior.
- Unit: `tests/test_lyrics_clients.py`
  - Mocks LRCLIB exact hit, LRCLIB miss, lyrics.ovh fallback hit, lyrics.ovh miss, and instrumental/no-lyrics cases.
- Unit: `tests/test_s3_storage.py`
  - Validates JSONL serialization, S3 key layout, dry-run writes, run metadata payload, and no secret leakage.
- Integration-style mocked: `tests/test_extract_pipeline.py`
  - Runs the extraction orchestrator against mocked Spotify/LRCLIB/lyrics.ovh/S3 clients and asserts max `150` track cap, dedupe, fallback order, and output counts.
- Live tests:
  - Out of scope for default CI/test command.
  - Optional future command can be gated by `RUN_LIVE_API_TESTS=1`.

## Validation

- Install/update env:
  - `uv sync`
- Format:
  - `uv run ruff format --check src tests scripts`
- Lint:
  - `uv run ruff check src tests scripts`
- Types:
  - `uv run mypy src tests`
- Tests:
  - `uv run pytest`
- Local extraction:
  - `uv run music-recommender-extract --seeds docs/base.md --output local --max-tracks-per-artist 5`
- S3 bootstrap:
  - `bash scripts/bootstrap_s3_medallion.sh`
- S3 extraction:
  - `uv run music-recommender-extract --seeds docs/base.md --output s3 --max-tracks-per-artist 150 --bucket "$MUSIC_RECOMMENDER_BUCKET"`
- Optional audio features run:
  - `ENABLE_SPOTIFY_AUDIO_FEATURES=true uv run music-recommender-extract --seeds docs/base.md --output s3 --max-tracks-per-artist 150 --bucket "$MUSIC_RECOMMENDER_BUCKET" --enable-audio-features`

## Risks and Mitigations

- Spotify audio features may be inaccessible for this app.
  - Mitigation: make audio features optional, record source availability in run metadata, and never fail the whole extraction on access errors.
- Spotify API rate limits may interrupt large extraction runs.
  - Mitigation: use `Retry-After`, exponential backoff, per-source throttling, and resumable run metadata later if needed.
- Spotify policy restricts using Spotify content to train ML/AI models.
  - Mitigation: for this phase, store catalog metadata for educational data collection only; future recommender training should prioritize non-Spotify/open signals such as lyrics, Last.fm tags, ListenBrainz, MusicBrainz, or AcousticBrainz.
- Lyrics coverage may be incomplete.
  - Mitigation: LRCLIB first, lyrics.ovh fallback, explicit `match_status`, and missing-lyrics records for observability.
- Artist name ambiguity can select wrong Spotify artists.
  - Mitigation: exact normalized name matching first, alias map, candidate metadata logging, and unresolved artist report.
- Duplicate songs across albums/singles/compilations can inflate counts.
  - Mitigation: dedupe by ISRC first, then normalized title/artist/duration fallback.
- S3 bucket naming can collide globally.
  - Mitigation: default bucket includes AWS account and region; allow override via `MUSIC_RECOMMENDER_BUCKET`.

## Open Questions

- None

## Acceptance Criteria

- Running the CLI in local mode with `--output local --max-tracks-per-artist 5` creates local JSONL outputs under `data/local/<run_id>/` without requiring S3.
- Running the CLI in S3 mode with `--output s3 --bucket "$MUSIC_RECOMMENDER_BUCKET"` uploads JSONL outputs to the configured S3 bucket.
- Running `bash scripts/bootstrap_s3_medallion.sh` creates/verifies the target S3 bucket and medallion prefixes using AWS CLI.
- Running the real extraction writes bronze Spotify catalog records and lyrics records to S3.
- No seed artist emits more than `150` deduped tracks.
- Lyrics use LRCLIB first and lyrics.ovh only when LRCLIB misses.
- Audio features are extracted only when enabled and accessible; inaccessible audio features do not fail the pipeline.
- Run metadata includes counts for seeds, resolved artists, albums, tracks, lyrics hits, lyrics misses, audio feature availability, errors, and S3 output paths.
- `.env` remains ignored and no secret values are committed.

## Definition of Done

- Python package, CLI, source clients, S3 storage, and medallion bootstrap script are implemented.
- `.env.example`, `README.md`, and `docs/data-extraction.md` document how to run the extraction safely.
- Unit and mocked integration tests are added.
- `uv run ruff format --check src tests` passes.
- `uv run ruff check src tests` passes.
- `uv run mypy src tests` passes.
- `uv run pytest` passes.
- Plan is updated if implementation scope changes.

## Research Sources

- Spotify API calls: https://developer.spotify.com/documentation/web-api/concepts/api-calls
- Spotify client credentials flow: https://developer.spotify.com/documentation/web-api/tutorials/client-credentials-flow
- Spotify search endpoint: https://developer.spotify.com/documentation/web-api/reference/search
- Spotify get artist albums endpoint: https://developer.spotify.com/documentation/web-api/reference/get-an-artists-albums
- Spotify get album tracks endpoint: https://developer.spotify.com/documentation/web-api/reference/get-an-albums-tracks
- Spotify get track endpoint: https://developer.spotify.com/documentation/web-api/reference/get-track
- Spotify get audio features endpoint: https://developer.spotify.com/documentation/web-api/reference/get-audio-features
- Spotify 2026 migration guide: https://developer.spotify.com/documentation/web-api/tutorials/february-2026-migration-guide
- Spotify 2024 Web API changes: https://developer.spotify.com/blog/2024-11-27-changes-to-the-web-api
- LRCLIB Python API docs: https://lrclibapi.readthedocs.io/en/stable/lrclib.html
- Last.fm API docs: https://www.last.fm/api
- MusicBrainz API docs: https://musicbrainz.org/doc/MusicBrainz_API
- ListenBrainz dumps: https://listenbrainz.readthedocs.io/en/latest/users/listenbrainz-dumps.html
- AWS Athena with Glue Data Catalog for S3 data: https://docs.aws.amazon.com/athena/latest/ug/data-sources-glue.html
