# Spotify Profile Data And S3 Deployment Readiness

## Goal

- Implement the missing repo work so the project can extract recommender data from both seed artists and the authenticated Spotify user profile, write the required medallion datasets to S3, and run the API against S3-backed data with durable AWS runtime state.

## Request Snapshot

- User request: "check the current status of the repo, whats missing to fetch the data not only for seeded data but also for my user profile in spotify, and also whats missing to deploy it in s3; create a plan to implement the missing steps"
- Owner or issue: `music-recommender-pkn`
- Plan file: `plans/20260709-1204-spotify-profile-s3-deployment.md`

## Current State

- Git status before creating this plan was clean on `main` tracking `origin/main`.
- Beads status:
  - `music-recommender-eaf` is still open for live demo credential setup, but the local `.env` now has a Spotify user refresh token.
  - `music-recommender-tfy` is closed for the deterministic recommender core.
- Local catalog data is usable:
  - `uv run music-recommender-demo-readiness check-data --data-root data/local` returned ready.
  - Selected run: `data/local/20260522052343-7123c483`
  - `silver/tracks`: 609 rows
  - `silver/audio_features`: 429 rows
- Spotify user OAuth is usable:
  - `uv run music-recommender-demo-readiness refresh-spotify-token` returned `access_token_present: true` and no missing required scopes.
  - `uv run music-recommender-demo-readiness check-live-profile --include-playlists` returned sample counts for saved tracks, top tracks, top artists, and playlists for `user_id: 12175364859`.
  - `.env` has `SPOTIFY_USER_REFRESH_TOKEN`, app client ID, and app client secret present. `SPOTIFY_DEMO_USER_ID` and `SPOTIFY_USER_SCOPES` are empty locally, but `load_settings()` defaults them to `12175364859` and `user-top-read user-library-read playlist-read-private playlist-modify-private playlist-modify-public`.
- AWS CLI is configured and usable:
  - `aws configure get region` returned `us-east-1`.
  - `aws sts get-caller-identity` returned account `571600852509`.
  - `aws s3api head-bucket --bucket music-recommender-571600852509-us-east-1` succeeded.
  - `aws s3api list-objects-v2 --bucket music-recommender-571600852509-us-east-1 --max-items 20` showed only `.keep` files under `bronze/`, `silver/`, `gold/`, and `metadata/`.
  - No CloudFormation stack containing `music-recommender` was found in `CREATE_COMPLETE`, `UPDATE_COMPLETE`, `UPDATE_ROLLBACK_COMPLETE`, or `ROLLBACK_COMPLETE`.

## Findings

- `src/music_recommender/pipeline/extract.py` extracts catalog data from `docs/base.md` seed artists only. It does not use the authenticated Spotify user's saved tracks, top tracks, top artists, or playlists as extraction inputs.
- `src/music_recommender/recommender/profile.py` already has a strong live Spotify profile sync path through `SpotifyProfileSyncService`, including saved tracks, top tracks/artists, playlist tracks, optional recently played tracks, source counts, affinities, and cached Spotify track candidates.
- `src/music_recommender/api/services.py` uses `JsonProfileCache` from `RECOMMENDER_PROFILE_CACHE_PATH` during recommendations, so local API personalization can use the synced Spotify profile.
- The live Spotify profile path currently stores a local JSON profile cache, not medallion datasets under `bronze/`, `silver/`, or `gold/`, and not S3.
- The profile sync path enriches runtime recommendations but does not create durable training or analytics tables such as `gold/user_profile_track_interactions` or `gold/user_track_interactions` for the authenticated Spotify user.
- `src/music_recommender/storage/s3.py` can write JSONL/Parquet to S3, and `scripts/bootstrap_s3_medallion.sh` can create the bucket/prefix placeholders.
- `src/music_recommender/pipeline/extract.py` and `src/music_recommender/pipeline/network.py` write promoted `silver`/`gold` datasets with `dt=<yyyy-mm-dd>` partitions.
- `src/music_recommender/recommender/catalog.py` expects S3 recommender datasets at `s3://.../<layer>/<dataset>/run_id=<run_id>`. That does not match the current extractor's S3 output layout for `silver/tracks`, `silver/audio_features`, `silver/lyrics_nlp`, or `gold/catalog_user_track_interactions`.
- `infra/template.yaml` defines Lambda, API Gateway, S3 read permissions, Secrets Manager dynamic references, and DynamoDB tables, but `src/music_recommender/api/services.py` still uses local JSON stores for profile cache, sessions, playlists, and feedback.
- `infra/README.md` explicitly says the deployed API should not be treated as durable across Lambda instances until the DynamoDB adapters are wired.

## Scope

### In scope

- Add a Spotify user profile extraction pipeline that writes authenticated profile signals to local or S3 medallion datasets.
- Reuse the existing `SpotifyUserClient` and `SpotifyProfileSyncService` normalization rules instead of duplicating Spotify profile semantics.
- Align S3 recommender reads with the actual extractor output layout so the deployed API can read S3 datasets produced by this repo.
- Add an S3 readiness check that validates catalog and optional interaction/profile datasets from S3.
- Add durable AWS runtime store adapters for Lambda profile cache, recommendation sessions, feedback, and playlist idempotency.
- Update SAM infrastructure, deployment scripts, docs, and tests for the S3/AWS path.

### Out of scope

- No frontend or static website deployment.
- No training pipeline or model fine-tuning.
- No multi-user OAuth onboarding UI.
- No raw Spotify token storage in S3, DynamoDB tables, logs, or medallion datasets.
- No scraper-based lyric or Spotify data collection.
- No replacement of the existing local JSON demo path.

## File Plan

| Path | Action | Details |
| --- | --- | --- |
| `src/music_recommender/models.py` | modify | Add explicit records for Spotify user profile extraction, such as `SpotifyProfileSourceRecord`, `SpotifyProfileTrackSignalRecord`, and `SpotifyProfileArtistSignalRecord`, with `to_dict()` methods and no secret fields. |
| `src/music_recommender/pipeline/profile.py` | create | Implement `SpotifyProfileExtractor` and `SpotifyProfileExtractionOptions` to fetch saved tracks, top tracks/artists, playlists, optional recently played tracks, normalize them, and write profile medallion datasets. |
| `src/music_recommender/profile_cli.py` | create | Add `music-recommender-profile-extract` CLI with `--output local|s3`, `--bucket`, `--run-id`, `--run-date`, `--top-limit`, `--saved-limit`, `--top-time-ranges`, `--include-playlists`, `--playlist-limit`, `--playlist-track-limit`, `--include-recently-played`, `--market`, and `--file-format`. |
| `pyproject.toml` | modify | Register `music-recommender-profile-extract = "music_recommender.profile_cli:main"`. |
| `src/music_recommender/recommender/profile.py` | modify | Extract reusable profile signal normalization helpers so API sync and medallion profile extraction share weighting, dedupe, source counts, and candidate creation. Preserve old JSON cache compatibility. |
| `src/music_recommender/recommender/catalog.py` | modify | Make S3 catalog loading compatible with `dt=<date>` promoted datasets by reading `s3://<root>/<layer>/<dataset>/` and filtering records by `source_run_id`, with optional fallback to legacy `run_id=<run_id>` prefixes. |
| `src/music_recommender/recommender/data.py` | modify | Add S3 readiness support and helper filtering by `source_run_id`; keep local readiness behavior unchanged. |
| `src/music_recommender/demo_readiness_cli.py` | modify | Add `check-s3-data` or extend `check-data` with `--data-mode s3` to validate S3 catalog/profile readiness without printing secrets. |
| `src/music_recommender/storage/dynamodb.py` | create | Implement DynamoDB-backed profile cache, session store, feedback store, and playlist record store adapters using boto3 clients and JSON payloads. |
| `src/music_recommender/recommender/sessions.py` | modify | Keep the existing protocol and add any serialization helpers needed by the DynamoDB session adapter. |
| `src/music_recommender/recommender/feedback.py` | modify | Introduce a small `FeedbackStore` protocol so `FeedbackService` can accept JSON or DynamoDB implementations. |
| `src/music_recommender/recommender/playlists.py` | modify | Introduce a `PlaylistRecordStore` protocol so `PlaylistService` can accept JSON or DynamoDB implementations. |
| `src/music_recommender/api/services.py` | modify | Select JSON stores for local mode and DynamoDB stores when table env vars are configured; keep existing local behavior as default. |
| `src/music_recommender/config.py` | modify | Add typed settings for runtime store backend and table names: `USERS_TABLE_NAME`, `SESSIONS_TABLE_NAME`, `FEEDBACK_TABLE_NAME`, and `PLAYLISTS_TABLE_NAME` or a documented decision to store playlist idempotency inside sessions. |
| `src/music_recommender/api/app.py` | modify | Add health/config presence fields for DynamoDB store configuration and S3 data readiness if lightweight enough. |
| `infra/template.yaml` | modify | Add any missing table/env wiring for profile cache and playlist idempotency; keep S3 permissions scoped to the configured bucket/prefix. |
| `scripts/upload_local_run_to_s3.sh` | create | Optional helper to upload an existing local run to the S3 medallion layout when a full re-extraction is not needed. Prefer `aws s3 sync` or the Python storage API with explicit source/destination validation. |
| `scripts/deploy_api_sam.sh` | create | Optional wrapper for `uv export`, `sam build`, and `sam deploy` with required parameter checks. |
| `README.md` | modify | Document seed catalog extraction, Spotify profile extraction, S3 upload, S3 readiness check, and deployed API configuration. |
| `docs/data-extraction.md` | modify | Add profile medallion datasets and document the S3 reader partition contract. |
| `docs/local-demo-runbook.md` | modify | Update local status to reflect working Spotify OAuth and add the profile extraction command. |
| `infra/README.md` | modify | Replace the current warning about local JSON Lambda state after DynamoDB adapters are implemented, and add exact deploy/validation commands. |
| `tests/test_profile_sync.py` | modify | Cover shared normalization helpers after extraction refactor so API profile sync behavior does not regress. |
| `tests/test_profile_extraction.py` | create | Cover profile medallion writes for saved/top/playlist/recent signals, source counts, dedupe, no secret fields, and S3/local storage modes with fakes. |
| `tests/test_recommender_data.py` | modify | Cover S3 `dt=<date>` partition reads filtered by `source_run_id`, plus fallback to legacy `run_id=<run_id>` prefixes. |
| `tests/test_demo_readiness_cli.py` | modify | Cover S3 readiness command with a fake S3 client or extracted helper. |
| `tests/test_api_health.py` | modify | Cover new runtime store config presence fields. |
| `tests/test_infra_template.py` | modify | Cover new DynamoDB table/env wiring and S3 permissions. |
| `tests/test_dynamodb_stores.py` | create | Cover DynamoDB store adapters with fake clients or botocore stubs; no live AWS calls in CI. |

## Data and Contract Changes

- New profile extraction CLI command:
  - `uv run music-recommender-profile-extract --output local|s3 --file-format parquet ...`
- New medallion datasets, recommended:
  - `bronze/spotify/user_profile/run_id=<profile-run-id>/part-000.parquet`
  - `bronze/spotify/saved_tracks/run_id=<profile-run-id>/part-000.parquet`
  - `bronze/spotify/top_tracks/run_id=<profile-run-id>/part-000.parquet`
  - `bronze/spotify/top_artists/run_id=<profile-run-id>/part-000.parquet`
  - `bronze/spotify/playlists/run_id=<profile-run-id>/part-000.parquet`
  - `bronze/spotify/playlist_tracks/run_id=<profile-run-id>/part-000.parquet`
  - `silver/user_profile_track_signals/dt=<yyyy-mm-dd>/part-000.parquet`
  - `silver/user_profile_artist_signals/dt=<yyyy-mm-dd>/part-000.parquet`
  - `gold/user_profile_track_interactions/dt=<yyyy-mm-dd>/part-000.parquet`
  - `metadata/runs/run_id=<profile-run-id>.json`
- Profile signal fields should include:
  - `user_id_hash` or configured demo user ID where needed for local demo; avoid email and tokens.
  - `spotify_track_id`, track name, artist names, signal source, time range, playlist ID/name when applicable, weight, and `source_run_id`.
  - `spotify_artist_id` when available, artist name, signal source, time range, weight, and `source_run_id`.
- Existing `/profile/sync`, `/profile`, `/recommendations`, `/feedback`, and `/playlists` routes remain stable.
- S3 reader contract should support the existing extractor layout:
  - Promoted datasets live under `silver/<dataset>/dt=<date>/...` and `gold/<dataset>/dt=<date>/...`.
  - Readers filter by `source_run_id == <run_id>` for deployed API requests.
- AWS runtime state contract:
  - Secrets remain in Secrets Manager.
  - S3 holds extracted datasets only.
  - DynamoDB holds runtime state such as profile cache, sessions, feedback, and playlist idempotency.

## Implementation Steps

1. Factor profile normalization out of `SpotifyProfileSyncService.sync_profile`.
   - Keep output-compatible `ProfileSnapshot`.
   - Add internal helpers that can return normalized track/artist signal rows in addition to `UserTasteProfile`.
   - Preserve current unit tests before changing the extraction flow.

2. Implement `src/music_recommender/pipeline/profile.py`.
   - Fetch current user, saved tracks, top tracks/artists across requested time ranges, playlists, playlist items, and optional recent plays through `SpotifyUserClient`.
   - Deduplicate by Spotify track ID and keep the strongest weight.
   - Write bronze raw-ish source rows with only non-secret Spotify payloads needed for audit/debug.
   - Write silver/gold profile signal rows with `source_run_id`.
   - Write run metadata with counts and skipped/inaccessible source notes.

3. Add `music-recommender-profile-extract`.
   - Load `.env` through existing settings.
   - Validate `SPOTIFY_USER_REFRESH_TOKEN`, bucket requirements, limits, and file format.
   - Use `S3Storage` exactly like catalog and network extraction.
   - Print `ExtractionSummary` JSON.

4. Fix S3 recommender dataset loading.
   - Update S3 mode in `load_recommender_catalog_from_run` to read promoted `dt=<date>` datasets and filter by `source_run_id`.
   - Keep local mode unchanged because local runs are already namespaced under `data/local/<run_id>/`.
   - Add tests proving data written with the documented extractor layout can be read by the deployed API path.

5. Add S3 readiness checks.
   - Validate `silver/tracks`, `silver/audio_features`, optional `silver/lyrics_nlp`, optional `gold/catalog_user_track_interactions`, and optional profile signal datasets from S3.
   - Return row counts, file counts, and missing datasets without dumping records.

6. Add DynamoDB runtime stores.
   - Implement small store adapters around current JSON serialization contracts.
   - Keep JSON stores as the default for local development.
   - Select DynamoDB stores in Lambda when the relevant table env vars are present.
   - Add idempotency behavior for playlist records equivalent to `JsonPlaylistRecordStore`.

7. Update SAM infrastructure.
   - Add any missing table for profile cache and playlist records, or explicitly store those payloads in the existing users/sessions tables.
   - Ensure env vars match `config.py` and `api/services.py`.
   - Keep IAM least-privilege access for S3 prefixes, Secrets Manager secret prefix, and DynamoDB tables.

8. Add deployment helpers and docs.
   - Document the sequence:
     1. Bootstrap or verify S3 bucket.
     2. Extract seed catalog to S3.
     3. Extract Spotify profile to S3.
     4. Run S3 readiness checks.
     5. Create or update the Secrets Manager runtime secret.
     6. Build/deploy SAM.
     7. Call `/health`, `/profile/sync`, `/recommendations`, `/feedback`, and `/playlists`.
   - Make clear that S3 stores datasets and Lambda/API Gateway runs the API; the API itself is not deployed "in S3".

9. Validate locally and with mocked AWS clients.
   - Run focused tests first.
   - Run full Ruff, mypy, and pytest before deploy.

10. Perform manual AWS validation after code is merged.
   - Upload or extract catalog/profile data to `s3://music-recommender-571600852509-us-east-1/`.
   - Confirm S3 object counts and readiness.
   - Deploy the SAM stack.
   - Confirm API Gateway output and smoke-test live routes with redacted responses.

## Implementation Progress

- [x] Factor profile normalization out of `SpotifyProfileSyncService.sync_profile`.
- [x] Implement `src/music_recommender/pipeline/profile.py` for local/S3 Spotify profile medallion extraction.
- [x] Add `music-recommender-profile-extract` CLI and `pyproject.toml` entry point.
- [x] Fix S3 recommender loading to read promoted `dt=<date>` datasets by `source_run_id`, with legacy `run_id=<run_id>` fallback.
- [x] Add S3 data readiness support through `check_s3_recommender_data` and `music-recommender-demo-readiness check-s3-data`.
- [x] Add DynamoDB runtime stores.
- [x] Update SAM infrastructure for all runtime stores.
- [x] Add deployment helper scripts.
- [x] Update README and data extraction docs for profile extraction and S3 reader behavior.
- [x] Perform manual AWS S3 extraction validation.
- [ ] Perform manual API SAM deployment smoke validation.

## Manual AWS Validation Notes

- S3 catalog upload succeeded for bucket `music-recommender-571600852509-us-east-1` and catalog run `20260522052343-7123c483`.
- Spotify profile extraction to S3 succeeded for profile run `profile-20260709-live-smoke`, writing the required profile signal and interaction datasets.
- `music-recommender-demo-readiness check-s3-data` returned ready for both the catalog and profile datasets.
- `aws cloudformation validate-template --template-body file://infra/template.yaml` succeeded.
- API deployment smoke validation was not run because the local `sam` CLI is not installed and Secrets Manager does not yet contain `music-recommender/demo/runtime`.

## Tests

- Unit: `tests/test_profile_sync.py` should prove the existing API sync payload and cache remain backward compatible after normalization refactor.
- Unit: `tests/test_profile_extraction.py` should cover saved tracks, top time ranges, selected playlists, inaccessible playlists, optional recently played, dedupe, weights, source counts, and no secret fields.
- Unit: `tests/test_recommender_data.py` should cover S3 promoted `dt=<date>` partitions filtered by `source_run_id` and the legacy `run_id=<run_id>` fallback.
- Unit: `tests/test_demo_readiness_cli.py` should cover the S3 readiness command with fake S3 data.
- Unit: `tests/test_dynamodb_stores.py` should cover get/put/update/list behavior for profile, session, feedback, and playlist stores using fake boto3 clients or botocore stubs.
- Integration: `tests/test_recommendations_api.py` should cover recommendations reading S3-style catalog data and cached Spotify profile candidates without live Spotify or AWS.
- Regression: `tests/test_extract_pipeline.py`, `tests/test_s3_storage.py`, `tests/test_infra_template.py`, `tests/test_api_health.py`, `tests/test_playlists_api.py`, and `tests/test_feedback_api.py` should continue to pass.

## Validation

- Format: `uv run ruff format --check src tests`
- Lint: `uv run ruff check src tests`
- Types: `uv run mypy src tests`
- Focused tests:
  - `uv run pytest tests/test_profile_sync.py tests/test_profile_extraction.py tests/test_recommender_data.py tests/test_demo_readiness_cli.py tests/test_dynamodb_stores.py tests/test_infra_template.py`
- Full tests: `uv run pytest`
- Manual S3 extraction smoke test:
  - `bash scripts/bootstrap_s3_medallion.sh`
  - `uv run music-recommender-extract --seeds docs/base.md --output s3 --file-format parquet --audio-feature-source reccobeats --max-tracks-per-artist 150 --bucket "$MUSIC_RECOMMENDER_BUCKET" --run-id <catalog-run-id>`
  - `uv run music-recommender-profile-extract --output s3 --file-format parquet --bucket "$MUSIC_RECOMMENDER_BUCKET" --run-id <profile-run-id> --include-playlists`
  - `uv run music-recommender-demo-readiness check-s3-data --bucket "$MUSIC_RECOMMENDER_BUCKET" --catalog-run-id <catalog-run-id> --profile-run-id <profile-run-id>`
- Manual API deployment smoke test:
  - `uv export --format requirements-txt --no-hashes --output-file requirements.txt`
  - `sam build --template-file infra/template.yaml`
  - `sam deploy --guided --template-file .aws-sam/build/template.yaml`
  - `curl "$API_URL/health"`
  - `curl -H "X-API-Key: $RECOMMENDER_API_KEY" "$API_URL/profile"`
  - `curl -H "X-API-Key: $RECOMMENDER_API_KEY" -H "Content-Type: application/json" -d '{"prompt":"I want upbeat songs that still feel emotionally honest","limit":10}' "$API_URL/recommendations"`

## Risks and Mitigations

- Risk: S3 reader/extractor partition mismatch breaks deployed recommendations.
  - Mitigation: Fix S3 reader tests to use actual extractor-style `dt=<date>` paths and filter by `source_run_id`.
- Risk: Spotify profile datasets accidentally store private raw payloads or secrets.
  - Mitigation: Whitelist fields in profile extraction records; never store tokens, email, or full OAuth responses.
- Risk: Lambda runtime state remains ephemeral if JSON stores are used in AWS.
  - Mitigation: Wire DynamoDB adapters and update `infra/README.md` only after API services use them.
- Risk: Reading all S3 `dt` partitions can grow slow later.
  - Mitigation: Accept for class demo, but keep `source_run_id` filtering isolated so a manifest/index optimization can be added later.
- Risk: Spotify scopes drift because `.env` omits explicit `SPOTIFY_USER_SCOPES`.
  - Mitigation: Write the default scope set explicitly into local `.env` and Secrets Manager runtime secret during deployment.

## Open Questions

- None

## Acceptance Criteria

- A new profile extraction command can fetch the authenticated Spotify user's profile sources and write local or S3 Parquet medallion datasets without exposing secrets.
- S3 bucket `music-recommender-571600852509-us-east-1` contains non-placeholder catalog/profile datasets after the extraction commands run.
- The recommender API can load catalog data from S3 using a `catalog_run_id` produced by the existing extraction pipeline.
- The deployed Lambda/API Gateway stack uses DynamoDB-backed runtime state for profile cache, sessions, feedback, and playlist idempotency.
- Readiness commands can validate both local and S3 data paths with row counts.
- Documentation includes the exact seed catalog, Spotify profile, S3 readiness, and SAM deployment sequence.

## Definition of Done

- Code implemented for profile extraction, S3 reader alignment, S3 readiness checks, and AWS runtime stores.
- Tests added or updated for all changed modules.
- `uv run ruff format --check src tests`, `uv run ruff check src tests`, `uv run mypy src tests`, and `uv run pytest` pass.
- Manual AWS validation is recorded with redacted outputs.
- Beads issues for any remaining deploy-only follow-up are created before closing implementation work.
