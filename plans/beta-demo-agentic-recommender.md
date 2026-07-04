# Beta Demo Agentic Recommender

## Source Request

Create a master implementation plan for a beta/class-demo version of the natural-language music
recommender described in `docs/recommender-architecture.md`. The demo should have no frontend, use
API calls only, deploy on AWS, use the user's Spotify profile, include Spotify playlist creation,
use the repository's existing extracted data pipeline outputs, and build the agentic layer with the
OpenAI Agents SDK.

## Goals

- Provide a phased implementation roadmap that another agent can execute without guessing.
- Build a backend-only demo with JSON API calls for recommendation requests and playlist creation.
- Use OpenAI Agents SDK for intent parsing, orchestration, tool calls, guardrails, and tracing.
- Use the current Spotify profile as the personalization source through OAuth-authorized user data.
- Use existing extracted catalog, ReccoBeats audio features, lyrics NLP, and ListenBrainz-linked data
  as recommender inputs.
- Deploy the class demo on AWS with a practical architecture that can start serverless and evolve if
  latency or dependency size becomes a problem.

## Non-Goals

- No web or mobile frontend.
- No public multi-user launch in the first implementation pass.
- No training on Spotify content or Spotify-derived data.
- No dependence on Spotify's deprecated recommendations or audio-features endpoints.
- No paid third-party music APIs beyond OpenAI and normal AWS/Spotify platform usage.
- No full production-grade recommendation model in phase 1; start with transparent scoring and
  first-party feedback events.

## Assumptions

- This is a beta/demo class project, not a public product.
- The repo is currently a Python 3.12 package with CLI entry points, strict mypy, ruff, pytest,
  `httpx`, `boto3`, `pyarrow`, and dotenv conventions in `pyproject.toml`.
- `docs/recommender-architecture.md` is the product/architecture source of truth for the
  recommender concept.
- The existing extraction pipeline already produces local or S3 medallion datasets with Spotify
  catalog rows, lyrics, optional lyrics NLP, ReccoBeats audio features, and ListenBrainz-derived
  interaction data.
- A redacted `.env` check showed `SPOTIFY_APP_CLIENT_ID` and `SPOTIFY_APP_CLIENT_SECRET` are set.
  These app credentials are not enough by themselves for reading the user's profile or creating
  playlists; user OAuth scopes and a refresh token flow are still needed.
- The provided Spotify profile URL is `https://open.spotify.com/user/12175364859?si=27ffd150d471468d`;
  use `12175364859` as the initial demo Spotify user identifier when planning profile lookup,
  OAuth validation, and playlist ownership checks.
- `OPENAI_API_KEY` can be added to `.env` and to AWS Secrets Manager later. Do not commit it.
- The OpenAI Agents SDK supports Python agents, function tools, guardrails, sessions, and tracing;
  use these SDK primitives rather than hand-rolling an agent loop.
- FastAPI is a good first API layer because it matches the Python repo, validates requests and
  responses with Pydantic models, and exposes useful OpenAPI docs for a class demo.

## Open Questions

- Which AWS region should the demo use? Default to `us-east-1` if not specified.
- Should OpenAI tracing be enabled in the class demo environment by default, or only locally?
- Does the class demo require a live Spotify OAuth browser step during setup, or is it acceptable to
  generate a refresh token once and store it in `.env`/Secrets Manager?
- Should playlist creation create new playlists every time, or update a known demo playlist for
  repeatability?
- Should the API reject requests if the OAuth-authenticated Spotify account does not match
  `12175364859`, or should that check be a warning for local demos?

## Current Repo Context

- `docs/recommender-architecture.md` documents the hybrid architecture and recommends using an LLM
  only for intent parsing/orchestration, with deterministic retrieval and ranking.
- `pyproject.toml` defines package `music-recommender`, Python `>=3.12`, dependencies, dev tools,
  and console scripts `music-recommender-extract` and `music-recommender-network`.
- `.env.example` currently includes Spotify app credentials, S3 bucket, extraction settings,
  ReccoBeats/audio-feature settings, lyrics NLP settings, and ListenBrainz dump settings.
- `src/music_recommender/sources/spotify.py` currently implements client-credentials Spotify catalog
  calls. It does not yet implement user OAuth endpoints, refresh tokens, saved tracks, top items,
  user playlists, or playlist creation.
- `src/music_recommender/pipeline/extract.py` writes medallion outputs through `S3Storage` and uses
  Spotify, ReccoBeats, LRCLIB, lyrics.ovh, and optional lyrics NLP sources.
- `src/music_recommender/pipeline/network.py` links ListenBrainz listens to the extracted catalog
  and writes `gold/catalog_user_track_interactions`.
- `src/music_recommender/storage/s3.py` already supports JSONL and Parquet writes locally or to S3.
- `tests/` uses fake clients and local temp paths heavily, which is the right pattern for the API
  and agent demo tests too.
- Existing validation commands in `README.md`: `uv run ruff format --check src tests`,
  `uv run ruff check src tests`, `uv run mypy src tests`, and `uv run pytest`.
- Current working tree has an unrelated uncommitted change in `docs/base.md`; implementation agents
  must not stage or overwrite it unless explicitly asked.

## Backend/API Integration

### Recommended AWS Architecture

Start with AWS serverless for the class demo:

- API Gateway HTTP API or REST API as the public HTTPS entry point.
- Lambda running the FastAPI app via an adapter such as Mangum or Lambda Web Adapter.
- S3 for extracted catalog/feature Parquet datasets, using the same bucket/prefix conventions as
  the current pipeline.
- DynamoDB for demo state: OAuth token metadata, recommendation sessions, feedback events, and
  playlist creation records.
- AWS Secrets Manager for `OPENAI_API_KEY`, Spotify client secret, and Spotify refresh token.
- EventBridge Scheduler or manual CLI jobs for offline refresh tasks such as catalog extraction,
  profile sync, and feature refresh.
- CloudWatch Logs for API logs and Lambda errors.
- Optional X-Ray or OpenAI Agents SDK tracing for agent/tool observability.
- IAM roles scoped to only the S3 prefixes, DynamoDB tables, and Secrets Manager secret ARNs the
  service needs.

This is the default recommendation because it is cheap, explainable, and class-demo friendly.

Alternative AWS option if Lambda becomes painful:

- ECS Fargate service behind Application Load Balancer.
- Same S3, DynamoDB, Secrets Manager, and CloudWatch integrations.
- Use this if Lambda cold starts, package size, native dependencies, or long agent/recommender calls
  make serverless awkward.

Do not start with SageMaker, OpenSearch, Redis, Step Functions, or Bedrock unless a later phase
needs them. They add operational surface area without improving the first demo.

### API Contract

Add a backend API module with these first endpoints:

- `GET /health`
  - Returns service status, version, and whether required secrets/config keys are present.
  - Must not reveal secret values.
- `POST /recommendations`
  - Input: natural-language prompt, optional limit, optional market, optional taste controls,
    optional playlist creation flag.
  - Output: structured intent, ranked tracks, score breakdowns, short explanations, and an optional
    `playlist_candidate`.
- `POST /playlists`
  - Input: recommendation session ID, playlist name, description, selected Spotify track IDs.
  - Output: Spotify playlist ID, URL, tracks added, and any partial failures.
  - Side effect: creates or updates a Spotify playlist; must be guarded and idempotent.
- `POST /feedback`
  - Input: session ID, track ID, event type such as `like`, `dislike`, `hide_artist`, `save`,
    `skip`, or `refine`.
  - Output: persisted feedback event ID.
- `POST /spotify/auth/start` and `GET /spotify/auth/callback` for local/demo OAuth setup, or a CLI
  equivalent if the demo should avoid exposing auth endpoints.

### OpenAI Agents SDK Usage

Use the Agents SDK for orchestration, not for direct song invention:

- `Intent Agent`: turns user prompt into `MoodIntent`.
- `Recommendation Orchestrator Agent`: calls tools and returns the final API response.
- Function tools:
  - `load_user_profile`
  - `load_catalog_candidates`
  - `rank_recommendations`
  - `create_spotify_playlist`
  - `record_feedback`
- Guardrails:
  - Input guardrail for obviously unrelated or unsafe requests.
  - Output guardrail to ensure the final response contains only tracks returned by tools.
  - Tool guardrail or explicit approval flag for playlist creation.
- Sessions:
  - Use session state for iterative refinement only after single-turn recommendations work.
- Tracing:
  - Enable locally during development and decide whether to enable in AWS demo after reviewing
    what metadata is captured.

## Data Model And Persistence

### Local Models

Add Pydantic/dataclass models for:

- `MoodIntent`
- `RecommendationRequest`
- `RecommendationResponse`
- `RecommendationCandidate`
- `ScoreBreakdown`
- `UserTasteProfile`
- `SpotifyUserProfileSnapshot`
- `PlaylistCreateRequest`
- `FeedbackEvent`

### DynamoDB Tables

For a class demo, one single-table design is acceptable, but separate small tables are easier to
explain:

- `music-recommender-demo-users`
  - Key: `user_id`
  - Fields: Spotify account ID/hash, token secret reference, profile sync timestamps.
- `music-recommender-demo-sessions`
  - Key: `session_id`
  - Fields: prompt, intent JSON, recommendation IDs, created playlist ID, timestamps.
- `music-recommender-demo-feedback`
  - Key: `session_id`, sort key `event_timestamp#track_id`
  - Fields: feedback type, track ID, artist ID/name, metadata.

Tokens should not be stored directly in DynamoDB for the demo. Store refresh tokens and API keys in
Secrets Manager and store only secret names/ARNs in DynamoDB or configuration.

### S3 Data

Use the existing medallion outputs as recommender input:

- `silver/tracks`
- `silver/audio_features`
- `silver/lyrics_clean`
- `silver/lyrics_nlp`
- `gold/catalog_user_track_interactions`
- `metadata/runs`

For local development, allow the same readers to load from `data/local/<run_id>/...` so the demo can
run without AWS while still matching production data contracts.

### Environment And Secrets

Extend `.env.example`:

- `OPENAI_API_KEY=`
- `OPENAI_AGENT_MODEL=`
- `SPOTIFY_REDIRECT_URI=`
- `SPOTIFY_USER_REFRESH_TOKEN=`
- `SPOTIFY_DEMO_USER_ID=12175364859`
- `SPOTIFY_USER_SCOPES=user-top-read user-library-read playlist-modify-private playlist-modify-public`
- `RECOMMENDER_DATA_ROOT=`
- `RECOMMENDER_DATA_MODE=local|s3`
- `RECOMMENDER_DEMO_USER_ID=`
- `AWS_SECRETS_PREFIX=`

Never log these values. Tests should use fake values.

## Implementation Tasks

1. [x] Create a high-level backend package skeleton.
   - Files: `src/music_recommender/api/__init__.py`, `src/music_recommender/api/app.py`,
     `src/music_recommender/api/models.py`, `src/music_recommender/api/errors.py`
   - Notes: Add FastAPI as a dependency. Keep route handlers thin and move business logic into
     services so unit tests do not need ASGI.

2. [x] Add API and agent configuration.
   - Files: `src/music_recommender/config.py`, `.env.example`, `README.md`
   - Notes: Add OpenAI, Spotify OAuth, data-root, and AWS deployment settings. Validate required
     settings at startup without printing secret values.

3. [x] Add Spotify user OAuth support.
   - Files: `src/music_recommender/sources/spotify_user.py`, `tests/test_spotify_user_client.py`
   - Notes: Keep the existing client-credentials `SpotifyClient` for catalog extraction. Add a new
     user-scoped client for OAuth token refresh, current profile, top tracks/artists, saved tracks,
     playlist creation, and adding playlist items. Use `httpx.MockTransport` tests.

4. [x] Add a one-time demo auth setup path.
   - Files: `src/music_recommender/spotify_auth_cli.py` or API routes under
     `src/music_recommender/api/routes/spotify_auth.py`, `pyproject.toml`, `.env.example`
   - Notes: For class demo reliability, prefer a CLI that opens/copies the authorization URL and
     stores only a refresh token in local `.env` manually. If API auth endpoints are added, keep
     callback validation and state checking explicit.

5. [x] Add recommender data readers.
   - Files: `src/music_recommender/recommender/data.py`,
     `src/music_recommender/recommender/catalog.py`, `tests/test_recommender_data.py`
   - Notes: Load local or S3 Parquet for tracks, audio features, lyrics NLP, and catalog-linked
     interactions. Start with small in-memory tables for demo scale. Do not require live extraction
     during an API request. Phase 0 only added a local readiness check for required tracks and audio
     feature Parquet outputs; the full recommender reader remains Phase 1 work.

6. [x] Define recommendation domain models and deterministic scoring.
   - Files: `src/music_recommender/recommender/models.py`,
     `src/music_recommender/recommender/scoring.py`, `tests/test_recommender_scoring.py`
   - Notes: Implement `mood_fit`, `taste_affinity`, `novelty_bonus`, `popularity_prior`,
     diversity penalty, explicit filtering, and duplicate artist/track handling.

7. [x] Implement Spotify profile sync for the demo user.
   - Files: `src/music_recommender/recommender/profile.py`,
     `src/music_recommender/api/routes/profile.py`, `tests/test_profile_sync.py`
   - Notes: Fetch saved tracks/top items through user OAuth, normalize into `UserTasteProfile`, and
     store a cache in local JSON during development and DynamoDB in AWS. Respect rate limits and
     handle missing profile data gracefully.

8. [x] Implement the OpenAI Agents SDK layer.
   - Files: `src/music_recommender/agents/__init__.py`,
     `src/music_recommender/agents/intent.py`,
     `src/music_recommender/agents/tools.py`,
     `src/music_recommender/agents/orchestrator.py`,
     `tests/test_agent_tools.py`
   - Notes: Add `openai-agents` as a dependency. Use `Agent`, `Runner`, and `@function_tool`.
     Ensure tool functions call deterministic services and return typed JSON-compatible results.
     Tests should mock the model/runner or test tools separately so CI does not need OpenAI keys.

9. [x] Add guardrails and output validation.
   - Files: `src/music_recommender/agents/guardrails.py`,
     `tests/test_agent_guardrails.py`
   - Notes: Validate that final tracks come from the candidate/ranking tool output. Playlist
     creation requires an explicit request flag and should never happen as an accidental side
     effect of a broad prompt.

10. [x] Implement recommendation API endpoint.
    - Files: `src/music_recommender/api/routes/recommendations.py`,
      `src/music_recommender/api/app.py`, `tests/test_recommendations_api.py`
    - Notes: `POST /recommendations` should support read-only recommendation first and optional
      playlist creation later. Return intent, track list, explanations, score breakdowns, and
      session ID.

11. [x] Implement playlist creation endpoint.
    - Files: `src/music_recommender/api/routes/playlists.py`,
      `src/music_recommender/recommender/playlists.py`, `tests/test_playlists_api.py`
    - Notes: Make playlist creation idempotent by storing a session-to-playlist record. If adding
      tracks partially fails, return a partial-failure response instead of hiding the error.

12. [x] Implement feedback endpoint.
    - Files: `src/music_recommender/api/routes/feedback.py`,
      `src/music_recommender/recommender/feedback.py`, `tests/test_feedback_api.py`
    - Notes: Store feedback locally first, then DynamoDB in the AWS phase. Feedback should influence
      later ranking only after persistence is stable.

13. [x] Add AWS infrastructure as code.
    - Files: `infra/README.md`, `infra/cdk/` or `template.yaml`
    - Notes: Prefer AWS CDK if the class can support it; otherwise use AWS SAM. Define API Gateway,
      Lambda, IAM roles, DynamoDB tables, Secrets Manager secret references, S3 bucket/prefix
      permissions, and CloudWatch log retention.

14. [x] Add AWS Lambda adapter and deployment entry point.
    - Files: `src/music_recommender/api/lambda_handler.py`, `pyproject.toml`,
      `tests/test_lambda_handler.py`
    - Notes: Use Mangum or Lambda Web Adapter. If package size or cold starts become a problem, add
      an ECS Fargate alternative in `infra/README.md` instead of overcomplicating Lambda.

15. [x] Add operational scripts for the demo.
    - Files: `scripts/demo_sync_profile.sh`, `scripts/demo_recommend.sh`,
      `scripts/demo_create_playlist.sh`, `README.md`
    - Notes: Scripts should use `curl` against local or deployed API. Do not embed secrets in
      scripts.

16. [ ] Update docs with the phase runbook.
    - Files: `README.md`, `docs/recommender-architecture.md`,
      `docs/beta-demo-runbook.md`
    - Notes: Document local setup, `.env` values, Spotify OAuth setup, OpenAI key setup, local API
      run command, AWS deploy command, and class demo flow.

17. [ ] Add phased Beads issues before implementation.
    - Files: Beads only
    - Notes: Create separate issues for API skeleton, Spotify OAuth, data reader/scoring, Agents SDK
      layer, playlist side effects, AWS deployment, and docs/runbook. Link dependencies so the work
      can be implemented incrementally.

## Phased Build Recommendation

### Phase 0: Data And Credentials Readiness

- Confirm a recent extraction run exists locally or in S3.
- Confirm `.env` has Spotify app credentials.
- Add `OPENAI_API_KEY` locally.
- Add Spotify OAuth redirect URI in the Spotify developer dashboard.
- Generate a user refresh token with required scopes.

Exit criteria:

- A local script can read extracted Parquet tracks/audio features.
- A local script can refresh a Spotify user access token.
- No API server or agent is required yet.

Implementation status on 2026-07-02:

- Added `music-recommender-demo-readiness check-data`, which reads local `silver/tracks` and
  `silver/audio_features` Parquet outputs and reports row counts.
- Added `music-recommender-demo-readiness auth-url`, `exchange-code`, and
  `refresh-spotify-token` for the one-time Spotify user OAuth flow.
- Added Spotify user OAuth support for token refresh, current profile, top items, saved tracks,
  playlist creation, and adding playlist items.
- Confirmed the local `smoke-reccobeats-parquet` run has readable tracks/audio features.
- Live token refresh still requires adding `SPOTIFY_USER_REFRESH_TOKEN` to `.env`.

### Phase 1: Deterministic Recommender Core

- Build data readers, profile models, scoring, and explanations.
- Use fake/demo user profile data first, then wire live Spotify profile sync.

Exit criteria:

- Unit tests rank candidate tracks for a breakup/cheer-up prompt intent.
- No OpenAI call is required for deterministic scoring tests.

Implementation status on 2026-07-02:

- Added local/S3 dataset readers for Parquet and JSONL recommender inputs.
- Added a catalog loader that merges extracted tracks, audio features, lyrics NLP, and linked
  interaction records into `CatalogTrack` objects.
- Added deterministic recommendation domain models for mood intent, user taste, catalog tracks,
  score breakdowns, and ranked candidates.
- Added scoring for mood fit, taste affinity, novelty, popularity, diversity, explicit filtering,
  blocked artists, and duplicate track handling.
- Added tests for the breakup/cheer-up prompt scenario without OpenAI or live Spotify calls.

### Phase 2: Agentic Intent And Tool Orchestration

- Add OpenAI Agents SDK.
- Implement intent parsing agent and tool-backed orchestrator.
- Add guardrails ensuring the agent cannot invent songs outside tool results.

Exit criteria:

- A local command/API call takes natural language and returns ranked tracks with structured intent.
- Tests cover tool output validation and no-song-invention behavior.

Implementation status on 2026-07-03:

- Added `openai-agents` and a new `music_recommender.agents` package with intent parsing,
  JSON-safe tool payloads, orchestration, and guardrail validation.
- Added deterministic intent parsing for local demos and an injectable OpenAI Agents SDK parser for
  live runs.
- Added `music-recommender-agent recommend`, which loads local/S3 catalog data, accepts a natural
  language prompt, and returns structured ranked recommendations as JSON.
- Added tests for agent tools, guardrails, orchestration, and the CLI without requiring live OpenAI
  or Spotify calls.

### Phase 3: API-Only Demo

- Add FastAPI routes for health, recommendations, playlists, feedback, and profile sync.
- Add local API run command.

Exit criteria:

- `curl` can request recommendations.
- `curl` can create a Spotify playlist when explicitly requested.
- API tests pass without live OpenAI/Spotify calls by using fakes.

Implementation status on 2026-07-03:

- Added a FastAPI backend package with `/health`, `POST /recommendations`, `POST /playlists`,
  `POST /feedback`, `POST /profile/sync`, and `GET /profile`.
- Recommendation requests reuse `AgenticRecommendationService` and the existing local/S3
  recommender catalog readers. Local requests use deterministic intent parsing by default, with
  optional OpenAI Agents SDK orchestration when explicitly requested.
- Playlist creation is explicit and idempotent by recommendation session through a local JSON
  record store. Feedback and profile sync also use local JSON stores for the class demo path.
- Added `music-recommender-api` and curl scripts for profile sync, recommendation, and playlist
  creation. Live profile sync and playlist creation still require a valid
  `SPOTIFY_USER_REFRESH_TOKEN`.

### Phase 4: AWS Serverless Deployment

- Add infrastructure as code.
- Deploy API Gateway + Lambda + DynamoDB + Secrets Manager access + S3 read permissions.
- Configure environment variables and secrets.

Exit criteria:

- Deployed API health check succeeds.
- Deployed recommendation request returns results.
- Deployed playlist creation works for the authorized demo Spotify profile.

Implementation status on 2026-07-03:

- Started Phase 4 with an AWS SAM template for API Gateway, Lambda, DynamoDB demo tables, scoped S3
  read access, Secrets Manager prefix access, environment variables, log retention, and stack
  outputs.
- Added a Mangum Lambda handler around the FastAPI app and a minimal `/health` endpoint so the
  deployment foundation can be validated before Phase 3 recommendation and playlist routes land.
- Added focused tests for the health route, Lambda handler, and SAM template. Live AWS deployment,
  recommendation requests, and playlist creation remain blocked on the Phase 3 API routes and
  local/demo credentials.

### Phase 5: Demo Polish And Evaluation

- Add canned prompt examples.
- Add runbook and troubleshooting.
- Add feedback events and simple before/after reranking demo.

Exit criteria:

- The class demo can be run end to end in under 5 minutes.
- Failure modes are documented: missing data, missing secrets, expired refresh token, Spotify rate
  limits, OpenAI API errors, and empty candidate sets.

## Tests And Scenarios

- Unit tests:
  - `tests/test_spotify_user_client.py` for OAuth refresh, user profile reads, top tracks/artists,
    saved tracks, playlist creation, and add-items behavior.
  - `tests/test_recommender_data.py` for local/S3 Parquet readers with small fixtures.
  - `tests/test_recommender_scoring.py` for mood fit, taste affinity, diversity, explicit filters,
    blocked artists, and empty candidate sets.
  - `tests/test_agent_tools.py` for tool contracts without live OpenAI calls.
  - `tests/test_agent_guardrails.py` for no hallucinated tracks and playlist side-effect gating.
- Integration tests:
  - `tests/test_recommendations_api.py` with FastAPI test client and fake services.
  - `tests/test_playlists_api.py` with fake Spotify user client and idempotency checks.
  - `tests/test_feedback_api.py` with local fake persistence.
  - `tests/test_lambda_handler.py` only after Lambda adapter is added.
- UI/E2E scenarios:
  - None for frontend. Use scripted `curl` API scenarios instead.
- Regression scenarios:
  - Existing extraction commands must keep working.
  - Existing `music-recommender-extract` and `music-recommender-network` tests should not require
    OpenAI or user OAuth.
  - Existing client-credentials Spotify catalog extraction should remain separate from user OAuth.

## Validation Commands

```bash
uv run ruff format --check src tests
uv run ruff check src tests
uv run mypy src tests
uv run pytest
```

After API dependencies are added:

```bash
uv run pytest tests/test_recommendations_api.py tests/test_playlists_api.py tests/test_agent_tools.py
```

Manual local demo commands should be documented once implemented:

```bash
uv run uvicorn music_recommender.api.app:app --reload
curl -X POST http://127.0.0.1:8000/recommendations \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"I just broke up with my girlfriend and I want songs to cheer me up","limit":10}'
```

## Risks And Rollback

- Risk: Spotify app credentials are confused with user OAuth credentials.
  Mitigation: Keep `SpotifyClient` and `SpotifyUserClient` separate and document required scopes.
  Rollback: Disable profile sync and playlist routes; keep deterministic local demo.

- Risk: The agent invents tracks or explanations not backed by data.
  Mitigation: Require all final tracks to come from recommender tool output and validate final
  output IDs.
  Rollback: Bypass the agent and call deterministic scoring directly.

- Risk: Lambda cold start or package size is too high with OpenAI Agents SDK, PyArrow, and API
  dependencies.
  Mitigation: Keep Lambda package lean, avoid loading Parquet repeatedly per request, and cache data
  in module scope for demo scale.
  Rollback: Deploy the same FastAPI app to ECS Fargate behind an ALB.

- Risk: Playlist creation creates spam playlists during testing.
  Mitigation: Require explicit `create_playlist=true`, use idempotency by session ID, and support
  updating a fixed demo playlist.
  Rollback: Turn off playlist route or switch it to dry-run mode.

- Risk: S3 data is stale or missing.
  Mitigation: Add health checks that validate required prefixes and a local fixture fallback for the
  class demo.
  Rollback: Use checked-in small test fixtures for the demo path only.

- Risk: Secrets leak through logs, traces, API errors, or test fixtures.
  Mitigation: Redact config checks, never log token values, use fake tokens in tests, and review
  OpenAI tracing behavior before enabling it in AWS.
  Rollback: Disable tracing and rotate affected secrets.

## Handoff Notes

- Do not implement all phases at once. Start with data readers and deterministic scoring before
  adding the OpenAI Agents SDK.
- Do not read, print, commit, or expose real `.env` secret values. Only check presence.
- Use the provided Spotify profile ID `12175364859` as the intended demo account, but verify it
  against the authenticated Spotify user's profile after OAuth rather than trusting the public URL
  alone.
- Keep live OpenAI and Spotify calls out of CI tests. Use fakes and mocked HTTP transports.
- Keep user-scoped Spotify OAuth separate from existing app-scoped catalog extraction.
- Treat playlist creation as a side effect requiring explicit user/API intent.
- Use S3/Parquet outputs from the existing pipeline as the recommendation corpus; do not call live
  Spotify catalog endpoints in the recommendation request path except for playlist operations or
  profile sync.
- Preserve the unrelated local `docs/base.md` change unless the user explicitly asks to include it.

## Sources

- `docs/recommender-architecture.md`
- `README.md`
- `pyproject.toml`
- `src/music_recommender/sources/spotify.py`
- `src/music_recommender/pipeline/extract.py`
- `src/music_recommender/pipeline/network.py`
- `src/music_recommender/storage/s3.py`
- OpenAI Agents SDK docs via Context7 and official OpenAI docs.
- AWS Lambda/API Gateway docs via Context7.
- FastAPI docs via Context7.
