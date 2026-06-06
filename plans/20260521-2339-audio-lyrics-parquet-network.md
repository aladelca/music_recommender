# Audio Features, Lyrics NLP, Parquet, and Network Data

## Goal

- Extend the extraction roadmap so the project can replace restricted Spotify audio features with ReccoBeats, enrich lyrics with language and multilingual sentiment, write lake datasets as partitioned Parquet instead of JSONL, keep run metadata in JSON, and choose a realistic free source for user-item network data.
- Keep the implementation local-first with the same `--output local|s3` behavior, while making S3 outputs queryable as medallion Parquet datasets.
- Avoid paid APIs and avoid scraping unless there is no stable free API or public dataset.

## Request Snapshot

- User request: "Add ReccoBeats, include a way to get language of lyrics and sentiment with multilanguage support, create a plan, avoid JSON data tables if possible using partitioned Parquets, keep metadata in JSON, and brainstorm with research whether Spotify API can provide network data like who likes which song/album or whether another source is better."
- Owner or issue: `None`
- Plan file: `plans/20260521-2339-audio-lyrics-parquet-network.md`

## Current State

- `music-recommender-extract` reads seed artists from `docs/base.md`, resolves Spotify artists/albums/tracks, fetches lyrics from LRCLIB with `lyrics.ovh` fallback, and writes medallion outputs locally or to S3.
- Local output currently writes JSONL data files under `data/local/<run_id>/.../part-000.jsonl`; S3 mode writes the same keys to the configured bucket.
- `src/music_recommender/storage/s3.py` exposes `S3Storage.write_jsonl`, `S3Storage.write_json`, `medallion_jsonl_key`, and `run_metadata_key`.
- `src/music_recommender/pipeline/extract.py` writes these datasets today:
  - `bronze/seeds/artists`
  - `bronze/spotify/artists`
  - `bronze/spotify/albums`
  - `bronze/spotify/tracks`
  - `bronze/spotify/audio_features`
  - `bronze/lyrics/lrclib`
  - `bronze/lyrics/lyrics_ovh`
  - `silver/artists`
  - `silver/albums`
  - `silver/tracks`
  - `silver/lyrics_clean`
  - `metadata/runs`
- `src/music_recommender/sources/spotify.py` has optional Spotify audio features support, but the live endpoint returned `403` for the current app in the previous run investigation.
- A live ReccoBeats batch request with `curl` on 2026-05-22 returned `200` for `GET https://api.reccobeats.com/v1/audio-features?ids=...`, but returned only partial coverage for the tested IDs. The implementation must treat ReccoBeats misses as expected.
- Project dependencies are currently small: `boto3`, `httpx`, `python-dotenv`, and `PyYAML`; NLP and Parquet dependencies are not installed yet.

## Findings

- ReccoBeats is the right next audio-feature source. Its docs expose `GET /v1/audio-features` for multiple audio features, and live testing confirmed it can return Spotify-like fields such as `acousticness`, `danceability`, `energy`, `instrumentalness`, `key`, `liveness`, `loudness`, `mode`, `speechiness`, `tempo`, and `valence`.
- Spotify audio features should remain optional fallback only. Spotify announced on November 27, 2024 that new Web API use cases no longer get access to Audio Features, Audio Analysis, Recommendations, Related Artists, and several playlist endpoints.
- For lyric language detection, use fastText language identification first. It is lightweight, local, free, and supports 176 languages via `lid.176.ftz` or `lid.176.bin`.
- For multilingual sentiment, use `cardiffnlp/twitter-xlm-roberta-base-sentiment-multilingual` as the first model. It is a Hugging Face text-classification model fine-tuned on multilingual tweet sentiment. It is not lyric-specific, so scores should be treated as weak NLP features rather than ground truth.
- For storage, partitioned Parquet is a better fit than JSONL for the lake. PyArrow supports writing partitioned Parquet datasets locally and against file-store backends, and Parquet is easier to query later with Athena, DuckDB, Polars, Spark, or Glue.
- Spotify cannot provide public "who likes which song/album" network data. It can provide only the authorized current user's saved tracks/albums, top tracks/artists, followed artists, playlists, and recently played items through OAuth scopes such as `user-library-read`, `user-top-read`, and `user-read-recently-played`.
- For collaborative/network recommendation data, ListenBrainz is the best free/open starting point. Its public/listens dumps contain listens submitted by users and are updated regularly; this can support user-track interaction matrices after mapping recordings to local track identifiers.
- Last.fm is a secondary option. It can be useful for tags and user-specific recent/loved tracks when usernames are available, but it is less clean as a public large-scale network source than ListenBrainz.

## Brainstorm Synthesis

- Catalog/content signals:
  - Keep Spotify for artist, album, track metadata, ISRCs, popularity, and URLs.
  - Add ReccoBeats for audio descriptors because Spotify audio features are restricted for this app.
  - Keep LRCLIB/lyrics.ovh for lyrics, then enrich the selected lyric text with language and sentiment.
- User/network signals:
  - Do not try to scrape Spotify likes or listens. It is not exposed publicly and would create policy/privacy risk.
  - If the app later has real users, collect consented first-party Spotify OAuth data per user and store only what the user authorizes.
  - For the educational recommender now, ingest ListenBrainz dumps and build `user_id_hash -> recording/track -> listen_count` interactions.
- Storage:
  - Move data tables to Parquet by default.
  - Keep run metadata as JSON at `metadata/runs/run_id=<run_id>.json` because it is small, human-readable, and operational rather than an analytics table.

## Scope

### In scope

- Add a ReccoBeats source client with batch audio feature fetching by Spotify track IDs.
- Add CLI/config options to choose audio feature source: `none`, `reccobeats`, or `spotify`.
- Add lyrics NLP enrichment:
  - Language detection with fastText.
  - Multilingual sentiment with `cardiffnlp/twitter-xlm-roberta-base-sentiment-multilingual`.
  - Chunk long lyrics and aggregate predictions at the track level.
- Add Parquet output support for local and S3 runs.
- Default user-facing data tables to Parquet, while keeping JSONL as an optional compatibility format.
- Keep `metadata/runs/run_id=<run_id>.json` as the run manifest format in both local and S3 output modes.
- Add data contracts for:
  - `bronze/reccobeats/audio_features`
  - `silver/audio_features`
  - `silver/lyrics_nlp`
  - `bronze/network/listenbrainz`
  - `silver/network/listens`
  - optional `gold/user_track_interactions`
- Add a ListenBrainz network-data ingestion plan in code/docs so recommendations can later use collaborative filtering signals.
- Add tests for ReccoBeats parsing, Parquet writing, NLP aggregation, CLI options, and ListenBrainz record normalization.

### Out of scope

- Training the recommender model.
- Building a UI or OAuth login flow for real Spotify users.
- Scraping Spotify users, likes, playlists, or listening history.
- Paid lyrics/audio-feature/user-data providers.
- Fine-tuning sentiment or language models.
- Deploying Glue, Athena DDL, Lake Formation, Lambda, ECS, or scheduled cloud jobs.
- Fully migrating historical JSONL output files already written under `data/local` or S3.

## File Plan

| Path | Action | Details |
| --- | --- | --- |
| `pyproject.toml` | modify | Add optional runtime dependencies for Parquet and NLP: `pyarrow`, `transformers`, `torch`, `fasttext-wheel` or a documented fastText model loader. Consider `polars` for local reads but keep PyArrow as the writer. |
| `.env.example` | modify | Add non-secret config examples: `AUDIO_FEATURE_SOURCE=reccobeats`, `OUTPUT_FILE_FORMAT=parquet`, `ENABLE_LYRICS_NLP=false`, `LYRICS_LANGUAGE_MODEL=fasttext-lid-176`, `LYRICS_SENTIMENT_MODEL=cardiffnlp/twitter-xlm-roberta-base-sentiment-multilingual`, `LISTENBRAINZ_DUMP_PATH`. |
| `.gitignore` | modify | Ignore local model/cache artifacts if needed, for example `.cache/`, `models/`, or `*.ftz` only if the implementation downloads fastText locally inside the repo. Prefer external cache paths to avoid repo clutter. |
| `README.md` | modify | Document ReccoBeats, Parquet output, lyric NLP options, model download/cache behavior, and ListenBrainz as the recommended network-data source. |
| `docs/data-extraction.md` | modify | Update source priority, medallion layout, schemas, and limitations around Spotify audio features and Spotify user/network data. |
| `docs/network-data.md` | create | Explain why Spotify cannot provide public likes/listens, how OAuth user data differs from public datasets, and how to use ListenBrainz for collaborative filtering. |
| `src/music_recommender/config.py` | modify | Add typed settings for audio feature source, output file format, NLP enablement, model names/cache paths, and ListenBrainz dump path/source URL. |
| `src/music_recommender/cli.py` | modify | Add `--audio-feature-source none|reccobeats|spotify`, `--file-format jsonl|parquet`, `--enable-lyrics-nlp`, `--language-model`, `--sentiment-model`, and optional network ingestion command/subcommand. |
| `src/music_recommender/models.py` | modify | Add dataclasses for `ReccoBeatsAudioFeaturesRecord`, `LyricsNlpRecord`, `ListenBrainzListenRecord`, and `UserTrackInteractionRecord`. |
| `src/music_recommender/sources/reccobeats.py` | create | Implement batch `GET /v1/audio-features?ids=<comma-separated-spotify-track-ids>`, parse returned feature rows, map by Spotify URL/track ID and ISRC, and return explicit misses. |
| `src/music_recommender/nlp/__init__.py` | create | Package marker for local NLP helpers. |
| `src/music_recommender/nlp/language.py` | create | Implement fastText language detection wrapper with lazy model loading, UTF-8 cleanup, confidence score, and `unknown` fallback. |
| `src/music_recommender/nlp/sentiment.py` | create | Implement Hugging Face sentiment pipeline wrapper with lazy loading, chunking, batch inference, and aggregation into `negative`, `neutral`, `positive` scores. |
| `src/music_recommender/nlp/lyrics.py` | create | Coordinate lyric normalization, language detection, sentiment inference, and track-level `LyricsNlpRecord` creation. |
| `src/music_recommender/storage/s3.py` | modify | Add `write_records(..., file_format)` and `write_parquet(...)`; preserve `write_jsonl(...)` for compatibility. Add key builder for `.parquet` files. Keep `write_json(...)` and `run_metadata_key(...)` for JSON run metadata. |
| `src/music_recommender/storage/parquet.py` | create | Convert lists of dictionaries to PyArrow tables with stable schemas, flatten or serialize raw payloads safely, write local Parquet, and upload Parquet bytes to S3. |
| `src/music_recommender/pipeline/extract.py` | modify | Wire ReccoBeats batch fetching after track collection, run lyric NLP after lyrics selection, and write chosen file format for all medallion datasets. |
| `src/music_recommender/pipeline/network.py` | create | Implement ListenBrainz dump ingestion/normalization into listen records and interaction aggregates, with local/S3 and Parquet support. |
| `src/music_recommender/sources/listenbrainz.py` | create | Read local ListenBrainz dump files or downloaded archives, stream `.listens` JSON lines, normalize user/recording metadata, and expose generator APIs. |
| `tests/test_reccobeats_client.py` | create | Mock ReccoBeats responses, partial coverage, `404`, `429`, and feature parsing. |
| `tests/test_parquet_storage.py` | create | Verify local Parquet writes, S3 upload body/content type, partition key layout, empty-record behavior, and schema stability. |
| `tests/test_lyrics_nlp.py` | create | Mock language and sentiment model outputs, long lyric chunking, missing lyric handling, score aggregation, and multilingual examples. |
| `tests/test_listenbrainz_client.py` | create | Test ListenBrainz `.listens` parsing, user hashing, recording identifiers, bad-record skips, and interaction aggregation. |
| `tests/test_extract_pipeline.py` | modify | Add assertions for ReccoBeats audio features, lyrics NLP records, Parquet keys, and backward-compatible JSONL mode. |
| `tests/test_s3_storage.py` | modify | Cover `write_records` dispatch and `.parquet` medallion key generation. |

## Data and Contract Changes

- CLI options:
  - `--audio-feature-source none|reccobeats|spotify`, default `reccobeats`.
  - `--file-format parquet|jsonl`, default `parquet`.
  - `--enable-lyrics-nlp`, default follows env var and should start as disabled if install/runtime cost is a concern.
  - `--language-model fasttext-lid-176`, default.
  - `--sentiment-model cardiffnlp/twitter-xlm-roberta-base-sentiment-multilingual`, default.
  - `--listenbrainz-dump-path <path>`, for local public dump ingestion.
- Environment variables:
  - `AUDIO_FEATURE_SOURCE`
  - `OUTPUT_FILE_FORMAT`
  - `ENABLE_LYRICS_NLP`
  - `LYRICS_LANGUAGE_MODEL`
  - `LYRICS_SENTIMENT_MODEL`
  - `LYRICS_NLP_BATCH_SIZE`
  - `LISTENBRAINZ_DUMP_PATH`
  - `LISTENBRAINZ_USER_HASH_SALT`, optional local salt for hashing usernames before storage.
- ReccoBeats bronze record fields:
  - `run_id`
  - `source`
  - `spotify_track_id`
  - `isrc`
  - `status`
  - `raw`
  - `fetched_at`
- Silver audio feature fields:
  - `spotify_track_id`
  - `isrc`
  - `acousticness`
  - `danceability`
  - `energy`
  - `instrumentalness`
  - `key`
  - `liveness`
  - `loudness`
  - `mode`
  - `speechiness`
  - `tempo`
  - `valence`
  - `audio_feature_source`
  - `source_run_id`
- Lyrics NLP fields:
  - `spotify_track_id`
  - `lyrics_source`
  - `language`
  - `language_confidence`
  - `language_model`
  - `sentiment_label`
  - `sentiment_score`
  - `negative_score`
  - `neutral_score`
  - `positive_score`
  - `sentiment_model`
  - `chunk_count`
  - `source_run_id`
- Network listen fields:
  - `user_id_hash`
  - `listened_at`
  - `recording_mbid`
  - `artist_name`
  - `track_name`
  - `release_name`
  - `isrc`
  - `spotify_track_id`, nullable until matched
  - `source`
  - `source_run_id`
- Interaction aggregate fields:
  - `user_id_hash`
  - `item_id`
  - `item_id_type`, for example `spotify_track_id`, `isrc`, or `recording_mbid`
  - `listen_count`
  - `first_listened_at`
  - `last_listened_at`
  - `implicit_rating`, derived later from listen counts if needed
  - `source_run_id`
- Medallion Parquet layout:
  - `bronze/reccobeats/audio_features/run_id=<run_id>/part-000.parquet`
  - `silver/audio_features/dt=<yyyy-mm-dd>/part-000.parquet`
  - `silver/lyrics_nlp/dt=<yyyy-mm-dd>/part-000.parquet`
  - `bronze/network/listenbrainz/run_id=<run_id>/part-000.parquet`
  - `silver/network/listens/dt=<yyyy-mm-dd>/part-000.parquet`
  - `gold/user_track_interactions/dt=<yyyy-mm-dd>/part-000.parquet`
- JSON policy:
  - Data tables should default to Parquet.
  - `metadata/runs/run_id=<run_id>.json` can remain as a small human-readable run manifest.
  - Do not migrate run metadata to Parquet in this feature; metadata JSON is the expected contract.

## Implementation Steps

1. Add storage format support first:
   - Add `FileFormat = Literal["jsonl", "parquet"]` or an enum.
   - Add `medallion_data_key(layer, dataset, partition, file_format)`.
   - Add `S3Storage.write_records(key, records, file_format)`.
   - Implement `write_parquet` by converting record dictionaries into a PyArrow table and writing one `part-000.parquet` file.
   - Preserve current JSONL behavior for compatibility tests.
   - Leave `metadata/runs/run_id=<run_id>.json` written through `write_json(...)` regardless of `--file-format`.
2. Add ReccoBeats:
   - Create `ReccoBeatsClient` with shared HTTP retry/backoff behavior.
   - Implement batch chunks over Spotify track IDs.
   - Parse `content` rows from ReccoBeats.
   - Extract Spotify track ID from `href` when needed.
   - Emit hit/miss records so run summaries show coverage.
   - Update `DataExtractor` to call ReccoBeats after all tracks for an artist or after all tracks for the run. Prefer after all tracks for better batching.
3. Adjust audio feature source selection:
   - Replace `enable_audio_features: bool` with `audio_feature_source: Literal["none", "reccobeats", "spotify"]`.
   - Keep Spotify source available only for explicit fallback or comparison.
   - Update summary counts: `reccobeats_audio_feature_hits`, `reccobeats_audio_feature_misses`, `spotify_audio_feature_unavailable`.
4. Add lyric NLP modules:
   - Implement language detector with lazy model load.
   - Load `lid.176.ftz` from a configured cache path or download instructions, not committed to the repo.
   - Implement sentiment wrapper with `transformers.pipeline`.
   - Chunk lyrics to fit model max length; aggregate chunk probabilities with weighted average by chunk length.
   - Return `unknown`/`not_available` when lyrics are missing.
5. Wire lyric NLP into extraction:
   - Add `enable_lyrics_nlp` to `ExtractionOptions`.
   - After selecting the best lyric record, run NLP only when enabled and `plain_lyrics` exists.
   - Write `silver/lyrics_nlp` as Parquet/JSONL depending on `--file-format`.
6. Add ListenBrainz ingestion:
   - Create a separate pipeline entry point rather than mixing heavy network dumps into artist catalog extraction.
   - Accept a local dump path first; downloading huge public dumps should be a separate explicit action.
   - Stream records to avoid loading entire dumps into memory.
   - Hash user names before output.
   - Normalize listens to recording-level fields.
   - Add a matching step that joins ListenBrainz records to local Spotify tracks by ISRC first, then normalized `(artist_name, track_name)`.
   - Write `silver/network/listens` and optional `gold/user_track_interactions`.
7. Update docs and examples:
   - Show local Parquet run:
     - `uv run music-recommender-extract --seeds docs/base.md --output local --file-format parquet --audio-feature-source reccobeats --max-tracks-per-artist 5`
   - Show S3 Parquet run:
     - `uv run music-recommender-extract --seeds docs/base.md --output s3 --file-format parquet --audio-feature-source reccobeats --bucket "$MUSIC_RECOMMENDER_BUCKET" --max-tracks-per-artist 150`
   - Show NLP-enabled run:
     - `uv run music-recommender-extract --seeds docs/base.md --output local --file-format parquet --audio-feature-source reccobeats --enable-lyrics-nlp --max-tracks-per-artist 5`
   - Explain that sentiment is a feature proxy and may not represent literary meaning.

## Tests

- Unit: `tests/test_reccobeats_client.py`
  - Batch success parses all numeric audio fields.
  - Partial response creates misses for missing Spotify IDs.
  - `404`, `403`, and `429` do not fail the whole extraction.
  - Spotify ID is recovered from ReccoBeats `href`.
- Unit: `tests/test_parquet_storage.py`
  - `write_parquet` creates a valid local Parquet file readable by PyArrow.
  - S3 mode uploads bytes with `ContentType` like `application/octet-stream` or `application/vnd.apache.parquet`.
  - `medallion_data_key(..., "parquet")` returns `part-000.parquet`.
  - Empty datasets produce a stable schema or documented skip behavior.
- Unit: `tests/test_lyrics_nlp.py`
  - Missing lyrics return `language=unknown` and `sentiment_label=not_available`.
  - English and Spanish sample lyrics are routed through mocked language detection.
  - Long text chunking aggregates probabilities correctly.
  - Model wrappers are lazily loaded and can be mocked without downloading real models.
- Unit: `tests/test_listenbrainz_client.py`
  - Valid `.listens` rows normalize to listen records.
  - Invalid rows are skipped with logged warnings.
  - User IDs are hashed.
  - Interaction aggregation counts listens per user-item.
- Integration-style mocked: `tests/test_extract_pipeline.py`
  - Pipeline writes Parquet keys when `file_format="parquet"`.
  - Pipeline writes ReccoBeats audio features when selected.
  - Pipeline writes lyrics NLP records only when enabled.
  - JSONL mode still works for existing tests.
- Regression: `tests/test_spotify_client.py`
  - Existing Spotify audio feature unavailable behavior still works when source is `spotify`.

## Validation

- Install/update dependencies:
  - `uv sync`
- Format:
  - `uv run ruff format --check src tests`
- Lint:
  - `uv run ruff check src tests`
- Types:
  - `uv run mypy src tests`
- Tests:
  - `uv run pytest`
- Local Parquet smoke test:
  - `uv run music-recommender-extract --seeds docs/base.md --output local --file-format parquet --audio-feature-source reccobeats --max-tracks-per-artist 5`
- Local Parquet plus NLP smoke test:
  - `uv run music-recommender-extract --seeds docs/base.md --output local --file-format parquet --audio-feature-source reccobeats --enable-lyrics-nlp --max-tracks-per-artist 2`
- S3 Parquet smoke test:
  - `uv run music-recommender-extract --seeds docs/base.md --output s3 --file-format parquet --audio-feature-source reccobeats --max-tracks-per-artist 5 --bucket "$MUSIC_RECOMMENDER_BUCKET"`
- Optional network-data smoke test after implementation:
  - `uv run music-recommender-network --source listenbrainz --dump-path "$LISTENBRAINZ_DUMP_PATH" --output local --file-format parquet --limit 10000`

## Risks and Mitigations

- ReccoBeats may not cover every Spotify track.
  - Mitigation: batch fetch, record explicit misses, keep source coverage counts, and allow Spotify fallback only when the app has access.
- ReccoBeats API behavior/rate limits may be less documented than Spotify.
  - Mitigation: use conservative chunk sizes, retries, backoff, and configurable timeouts.
- Lyrics sentiment is domain-mismatched because the recommended model is trained for social sentiment, not song meaning.
  - Mitigation: label outputs as NLP feature proxies, keep model name/version in every row, and consider future emotion classification only after baseline data is working.
- Multilingual sentiment quality may vary by language.
  - Mitigation: store detected language and confidence, aggregate with confidence, and evaluate a small hand-labeled sample later.
- Transformer dependencies increase install size and runtime.
  - Mitigation: make NLP optional, lazy-load models only when `--enable-lyrics-nlp` is set, and keep default smoke tests mocked.
- Parquet schemas can break if raw nested API payloads vary.
  - Mitigation: flatten stable columns; for bronze raw payloads, either store a `raw_json` string inside Parquet or define explicit nested schemas per source.
- ListenBrainz dumps can be large.
  - Mitigation: stream files, add `--limit` for educational runs, write partitioned outputs, and keep download/import as a separate command.
- User network data has privacy implications.
  - Mitigation: use public ListenBrainz dumps according to their published terms, hash user identifiers in lake outputs, and require OAuth consent for any future first-party Spotify user data.

## Open Questions

- None

## Acceptance Criteria

- A local extraction can write Parquet data tables under `data/local/<run_id>/.../part-000.parquet`.
- An S3 extraction can write the same Parquet datasets under `s3://<bucket>/<layer>/<dataset>/<partition>/part-000.parquet`.
- The extraction can fetch ReccoBeats audio features in batch and report hit/miss counts without failing on missing tracks.
- Lyrics NLP can be enabled with a CLI flag and writes language plus sentiment rows for lyrics that exist.
- JSONL remains available only as `--file-format jsonl` compatibility mode.
- Run metadata remains JSON at `metadata/runs/run_id=<run_id>.json` in both local and S3 modes.
- The docs clearly state that Spotify cannot provide public who-liked/listened network data and recommend ListenBrainz for educational collaborative filtering.

## Definition of Done

- Code implements ReccoBeats batch audio features, optional lyrics NLP, Parquet storage, and the first ListenBrainz network ingestion path.
- New and updated tests cover the file-format switch, ReccoBeats partial coverage, NLP aggregation, and network record normalization.
- `uv run ruff format --check src tests`, `uv run ruff check src tests`, `uv run mypy src tests`, and `uv run pytest` pass.
- README and docs contain local and S3 commands for Parquet extraction, explain that run metadata remains JSON, and document the recommended network-data source.
- The plan is updated if implementation scope changes.

## Research Sources

- ReccoBeats API docs: https://reccobeats.com/docs/apis/get-audio-features
- Spotify Web API changes from November 27, 2024: https://developer.spotify.com/blog/2024-11-27-changes-to-the-web-api
- Spotify saved tracks endpoint: https://developer.spotify.com/documentation/web-api/reference/get-users-saved-tracks
- Spotify top items endpoint: https://developer.spotify.com/documentation/web-api/reference/get-users-top-artists-and-tracks
- Spotify OAuth scopes: https://developer.spotify.com/documentation/web-api/concepts/scopes
- ListenBrainz data dumps: https://listenbrainz.readthedocs.io/en/latest/users/listenbrainz-dumps.html
- fastText language identification: https://fasttext.cc/docs/en/language-identification
- CardiffNLP multilingual sentiment model: https://huggingface.co/cardiffnlp/twitter-xlm-roberta-base-sentiment-multilingual
- Apache Arrow Parquet docs: https://arrow.apache.org/docs/python/parquet.html
