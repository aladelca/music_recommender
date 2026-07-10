# Explainable Spotify Discovery Beta

## Source Request

Turn the existing single-user AWS music recommender into a product-first beta for five Spotify users. Each tester must sign in with their own Spotify account, receive recommendations based only on their own permitted signals, understand each recommendation through evidence cards, review and reorder tracks, explicitly name the playlist, and create that playlist in their own Spotify account. Deploy the frontend on Vercel, retain the Python backend and data pipeline on AWS, use Supabase when relational persistence is needed, leave the internal beta allowlist configurable until the five testers are known, deploy and test the complete system, and do not introduce CloudFront.

## Goals

- Deliver a mobile-responsive web application whose first screen is the actual Spotify sign-in and discovery workflow, not a marketing landing page.
- Support exactly five Spotify Development Mode testers for the initial beta, with a deny-by-default internal approval workflow in addition to Spotify's dashboard allowlist.
- Replace the shared API-key product experience with per-user Spotify OAuth, opaque application sessions, CSRF protection, and strict tenant isolation.
- Fetch and refresh each approved user's permitted Spotify top items, saved tracks, and selected playlist signals without relying on a repository-wide seeded demo user.
- Produce 10-track discovery sessions from the independent catalog in S3, excluding known tracks and blocked artists while honoring prompt, novelty, explicit-content, and adventure controls.
- Explain every recommendation with deterministic evidence cards that identify the taste anchor, discovery bridge, prompt match, evidence source, confidence limitation, and known/unknown status.
- Make recommendation review mandatory before Spotify side effects. Users can remove and reorder tracks, override the generated playlist name, choose public or private visibility, and then explicitly export.
- Ensure playlist export uses the logged-in user's token and Spotify's current `/me/playlists` and playlist `/items` APIs so the playlist appears in that same user's Spotify library.
- Persist multi-user identity, sessions, profile snapshots, recommendation history, feedback, playlist exports, and beta evaluations in Supabase Postgres.
- Keep Spotify OAuth/token custody and all privileged database access in the AWS backend. Store refresh tokens only as AWS KMS ciphertext.
- Deploy the Vite frontend through Vercel and proxy same-origin `/api/*` requests to AWS API Gateway using a Vercel external rewrite. CloudFront is not required.
- Operate profile synchronization asynchronously, with retries, dead-letter handling, monitoring, redacted logs, account deletion, and a documented reconnect flow.
- Run a structured five-tester beta that measures whether recommendations are perceived as better than the testers' usual Spotify discovery experience and whether explanations are useful.

## Non-Goals

- Monetization, subscriptions, billing, advertising, or a public launch.
- More than five Spotify Development Mode users or an Extended Quota Mode application during this phase.
- A native iOS/Android app, background playback, a full music player, or replacement of Spotify's core listening experience.
- CloudFront, S3 website hosting, Route 53, or a custom domain for the first beta. Vercel's stable production domain is sufficient.
- Supabase Auth. It does not manage or persist Spotify provider refresh-token rotation, so it does not remove the need for trusted backend token custody.
- Direct browser access to Supabase, exposure of a Supabase service key, or using Supabase row-level security as the primary application authentication mechanism.
- Training or fine-tuning an ML/AI model on Spotify Content, sending Spotify profile/catalog data to an LLM, or building cross-user behavioral profiles.
- Migrating historical single-user DynamoDB demo records into the beta database. The existing deployment remains available temporarily for rollback and comparison.
- Real-time collaborative playlists, social feeds, following other users, notifications, or administrator UI.
- Statistical claims of product superiority based on five users. The beta produces directional product evidence, not a generalizable scientific conclusion.
- Bundling Parquet or CSV data in Lambda or Vercel deployment artifacts. Existing private S3 datasets can remain in their current runtime format.

## Assumptions

- The beta product direction is the previously agreed explainable new-music discovery experience, provisionally named "Outside the Loop". The final brand can change without changing the architecture.
- The frontend will be a new React, TypeScript, and Vite application under `web/`. This keeps the static frontend deployable on Vercel and independent of the existing Python package.
- Vercel serves the frontend and already provides CDN/edge delivery. A rewrite from `/api/:path*` to API Gateway gives the browser a same-origin application surface, so CloudFront adds no required capability for this beta. See [Vercel external rewrites](https://vercel.com/docs/routing/rewrites).
- AWS account `571600852509`, region `us-east-1`, API stack `music-recommender-demo`, private S3 bucket `music-recommender-571600852509-us-east-1`, and the currently deployed API are the starting environment. Exact resource identifiers must be discovered from stack outputs during implementation rather than copied into application code.
- Supabase Postgres is selected for new product state because the beta requires relational user ownership, history, idempotency, surveys, cleanup, and cross-record integrity. Supabase Auth is intentionally not selected because [provider token refresh is application-managed and provider tokens are not stored by Supabase Auth](https://supabase.com/docs/guides/auth/social-login).
- The AWS API will connect to Supabase's transaction-mode pooler using TLS and backend-only credentials stored in AWS Secrets Manager. No database credential or privileged key is emitted into Vite environment variables.
- The stable Vercel production URL will be registered as the one Spotify redirect URI for the beta. Spotify requires an exact HTTPS redirect match; preview URLs will not run live OAuth. See [Spotify redirect URI requirements](https://developer.spotify.com/documentation/web-api/concepts/redirect_uri).
- Spotify Development Mode currently supports up to five allowlisted users and requires the app owner to have Premium. This beta remains within that boundary. See [Spotify quota modes](https://developer.spotify.com/documentation/web-api/concepts/quota-modes).
- The five tester identities are not known yet. First-time OAuth users will be recorded as `pending`; only a backend CLI can mark them `approved`. There will be no wildcard or permissive placeholder allowlist.
- `account_id`, introduced for the 2026 Development Mode migration, is the durable Spotify account key. Display name, image, email, and legacy user ID are optional and must not be identity dependencies. See the [May 2026 change note](https://developer.spotify.com/documentation/web-api/references/changes/may-2026).
- The minimum Spotify scopes remain `user-top-read`, `user-library-read`, `playlist-read-private`, `playlist-modify-private`, and `playlist-modify-public`. `user-read-recently-played` stays optional and disabled until there is a demonstrated recommendation-quality need.
- The production recommender is deterministic and local. An LLM may parse only the user's own free-text prompt into a bounded intent schema; it must never receive Spotify content, profile signals, candidate metadata, or recommendation results.
- The private S3 catalog is built from independent sources such as ListenBrainz and ReccoBeats, with Spotify identifiers used for linking/export. Spotify popularity must not be used as a ranking feature.
- Spotify metadata/artwork displayed by the UI will retain Spotify attribution and link back to Spotify, and playback will use the official Spotify Embed or an "Open in Spotify" action. See [Spotify design requirements](https://developer.spotify.com/documentation/design) and [Spotify Embed](https://developer.spotify.com/documentation/embeds/tutorials/using-the-iframe-api).
- The existing single-user API and DynamoDB tables can remain live under a compatibility flag until the multi-user deployment passes production smoke tests. No destructive table deletion is part of this plan.

## Open Questions

- Which five Spotify accounts will be added to the Spotify dashboard and approved internally? This does not block implementation because users can remain `pending` until account IDs are known.
- What Vercel project slug and final product name should be used? Default to `outside-the-loop-beta` and update copy/config once confirmed.
- Which Supabase organization, project reference, database region, and billing owner should be used? Prefer a US East region close to the AWS deployment.
- What public privacy contact and data-controller name should appear in the beta privacy notice? Use explicit placeholders that fail the production readiness check until replaced.
- Does the Spotify developer application owner currently satisfy the Premium and Development Mode requirements? Validate before inviting testers.
- Does a documented legal/policy review approve using the selected Spotify signals for this user-requested recommender? Implementation can proceed behind a disabled invite flag, but no tester invitations should be sent until the phase-zero policy gate is signed off.

## Current Repo Context

- The repository is a Python 3.12 package using FastAPI, Mangum, AWS SAM, S3, DynamoDB, and scheduled Lambda functions. There is no frontend or Node workspace today.
- `src/music_recommender/api/app.py` applies one optional `X-API-Key` to every protected route. That is suitable for the existing private demo but cannot identify or isolate five end users.
- `src/music_recommender/api/services.py` contains a single `DemoApiService`. It reads one cached profile, accepts caller-controlled `demo_user_id` and run IDs, can append Spotify profile tracks into the candidate catalog, persists to DynamoDB/JSON, and can create a playlist during recommendation generation.
- `src/music_recommender/config.py` contains one `SPOTIFY_USER_REFRESH_TOKEN`, one `SPOTIFY_DEMO_USER_ID`, four DynamoDB table names, and `RUNTIME_STORE_BACKEND=auto|local|dynamodb`. It has no app base URL, session, KMS, queue, or Supabase settings.
- `src/music_recommender/sources/spotify_user.py` already supports authorization-code exchange, refresh, current-user profile, top items, saved tracks, playlists, and playlist reads. Playlist writes still call removed/deprecated paths: `POST /users/{id}/playlists` and `POST /playlists/{id}/tracks`. They must become `POST /me/playlists` and `POST /playlists/{id}/items` per Spotify's [February 2026 migration guide](https://developer.spotify.com/documentation/web-api/tutorials/february-2026-migration-guide).
- `src/music_recommender/recommender/scoring.py` currently weights mood 65%, direct taste 20%, novelty 5%, and popularity 10%, then emits a score in explanation text. This does not prioritize discovery, uses pseudo-precise user-facing scores, and does not expose evidence provenance.
- `src/music_recommender/agents/orchestrator.py` and `src/music_recommender/agents/tools.py` can send catalog/profile-derived data through OpenAI tool calls when `use_openai_agent=true`. That production path conflicts with the intended Spotify data boundary and must be disabled before beta use.
- `src/music_recommender/recommender/profile.py` normalizes a single user's Spotify data into affinities and candidates. The implementation needs an account-scoped snapshot contract and must separate known/profile signals from the independent discovery candidate pool.
- `src/music_recommender/storage/dynamodb.py` implements users, sessions, feedback, and playlist stores with keys designed around one demo user/session. The interfaces are reusable, but the new product persistence needs account ownership and relational constraints.
- `infra/template.yaml` defines one API Lambda, one scheduled profile Lambda, four retained DynamoDB tables, API access logs, alarms, S3 access, and runtime secret references. It needs a KMS key, profile-sync SQS/DLQ, Supabase settings, new IAM grants, and multi-user scheduler behavior.
- `scripts/prune_lambda_artifacts.sh` and deployment tests already enforce Lambda package cleanup. The expanded build must continue proving no `.parquet` or `.csv` files are packaged.
- Existing tests cover API auth, recommendations, profile synchronization, feedback, playlist idempotency, Spotify client behavior, DynamoDB adapters, SAM structure, deployment scripts, and the deployed smoke flow. They provide regression coverage while the product API is introduced.
- Existing runbooks under `docs/` cover API use, AWS deployment, operations, and recommender methodology for the single-user product. They must be revised rather than duplicated.
- Current production state uses a shared API key and a single Spotify refresh token in Secrets Manager. Those values must remain functional only during the compatibility window and must not be copied into the browser or Supabase.

## Target Architecture

```text
Browser
  -> Vercel production domain
       -> React/Vite static application
       -> /api/* external rewrite
            -> API Gateway HTTP API
                 -> FastAPI/Mangum API Lambda
                      -> Spotify Accounts API (OAuth/token refresh)
                      -> Spotify Web API (profile reads/playlist writes)
                      -> Supabase Postgres transaction pooler
                      -> AWS KMS (refresh-token encrypt/decrypt)
                      -> private S3 catalog
                      -> SQS profile-sync queue
                 -> profile-sync worker Lambda
                      -> Spotify Web API
                      -> Supabase Postgres
                 -> EventBridge daily scheduler Lambda
                      -> Supabase approved-user query
                      -> SQS profile-sync queue

CloudWatch logs/metrics/alarms observe API, scheduler, worker, queue, and DLQ.
Secrets Manager holds Spotify, database, session, and optional prompt-parser secrets.
```

- Vercel is the public web edge. Do not add CloudFront in front of Vercel or API Gateway.
- The browser calls relative `/api` URLs. Production CORS is therefore not part of normal request flow; only explicit localhost origins are allowed for local development.
- AWS is the only trusted application backend. It owns OAuth state, session issuance, Spotify token refresh, authorization, recommendations, persistence access, and side effects.
- Supabase is a managed Postgres provider, not a second application backend. The browser does not use Supabase Auth or Data APIs.
- S3 remains private and is read only by AWS compute. Catalog objects are not routed through Vercel and are not embedded in deployment artifacts.

## Backend/API Integration

### Authentication And Session Contract

- `GET /auth/spotify/start?return_to=/discover`
  - Validate `return_to` against an internal path allowlist.
  - Generate 256-bit OAuth state and PKCE verifier/challenge.
  - Store only the state hash plus KMS-encrypted verifier, return path, creation time, and 10-minute expiry.
  - Redirect to Spotify with the exact configured production callback and minimum scopes.
- `GET /auth/spotify/callback?code=...&state=...`
  - Atomically consume the one-time state before code exchange; reject missing, expired, mismatched, or replayed state.
  - Exchange the code, call `/me`, use `account_id` as identity, KMS-encrypt the refresh token with `account_id` as encryption context, and never persist the access token.
  - Upsert the user as `pending` unless already `approved` or `revoked`.
  - Issue `__Host-mr_session` as a random opaque HttpOnly, Secure, SameSite=Lax, Path=/ cookie. Store only its SHA-256 hash. Use a 7-day idle and 30-day absolute lifetime.
  - Issue a readable `__Host-mr_csrf` Secure, SameSite=Lax cookie and store its hash with the session.
  - Redirect pending users to `/access-pending`; redirect approved users to onboarding or discovery and enqueue profile sync when stale.
- `GET /auth/me`
  - Return only application identity, access status, profile readiness, reauthorization status, and safe display fields. Never return Spotify or database tokens.
- `POST /auth/logout`
  - Require CSRF and allowed Origin, revoke the current hashed session, expire both cookies, and return `204`.
- `DELETE /account`
  - Require a recent session, CSRF, explicit confirmation text, and a reauthentication/recent-login window.
  - Revoke sessions, remove token ciphertext and all account-owned database records, and return `202` while cleanup finishes if Spotify revocation or asynchronous cleanup is required.
- Every product route derives `account_id` from the server-side session dependency. Request bodies must not accept `demo_user_id`, Spotify account IDs, or arbitrary profile IDs.
- Mutating requests require a valid session, matching CSRF cookie/header, and an allowed `Origin`. Authentication failures return `401`; pending/revoked access returns `403`; reconnect-required Spotify state returns `409` with a stable error code.
- Keep `AUTH_MODE=api_key|hybrid|spotify_session` during rollout. `hybrid` allows legacy smoke routes with the API key and new `/auth` product routes. Switch to `spotify_session` only after live beta validation.

### Beta Access Administration

- Implement backend CLI commands to list pending account IDs, approve one account, revoke one account, and report the approved count without printing refresh-token ciphertext or profile data.
- Enforce a database constraint and service guard that no more than five accounts can be `approved` in beta mode.
- Spotify's own developer-dashboard allowlist remains the outer gate. The CLI-managed status is the inner application gate.
- Do not seed fake account IDs and do not use `*`, empty-list-means-allow, or first-five-auto-approved behavior.

### Profile Synchronization

- `POST /profile/sync` enqueues one idempotent account-scoped sync job and returns `202` with `job_id`; it does not block an API Gateway request on multiple Spotify pages.
- `GET /profile/status` returns `not_started|queued|syncing|ready|failed|reconnect_required`, safe source counts, last sync time, and a redacted error code.
- `GET /profile/summary` returns user-facing anchors and source coverage needed for evidence display. It must not expose a raw Spotify response or synthetic personality labels.
- The API enqueues a sync after first approval/login and when the current snapshot is older than 24 hours.
- EventBridge runs daily. The scheduler queries approved, non-deleted users and sends one SQS job per stale user.
- The worker processes one account per invocation, decrypts that account's refresh token, refreshes/rotates it, fetches bounded pages, normalizes signals, writes a new snapshot transactionally, and updates job status.
- Retry Spotify `429` responses using `Retry-After`, retry bounded `5xx` failures with jitter, mark revoked/expired refresh tokens as `reconnect_required`, and never retry `403` missing-scope errors indefinitely.
- Refresh tokens can expire after six months and may rotate. Persist replacement ciphertext atomically and provide a reconnect action. See [Spotify refresh tokens](https://developer.spotify.com/documentation/web-api/tutorials/refreshing-tokens).

### Recommendation Contract

- `POST /recommendations` accepts:

```json
{
  "prompt": "Warm electronic music for a late-night walk",
  "limit": 10,
  "adventure": "balanced",
  "allow_explicit": false,
  "blocked_artist_ids": [],
  "anchor_track_id": null
}
```

- Public requests no longer accept `create_playlist`, `playlist_name`, `playlist_public`, `use_openai_agent`, catalog run IDs, interaction run IDs, liked IDs, known IDs, artist names, or user IDs.
- The service loads the authenticated user's current snapshot, the configured S3 catalog run, and first-party preferences. It returns `409 profile_not_ready` until a usable snapshot exists.
- Response items include Spotify track link/embed identifiers, display metadata, rank, and a structured evidence card. Internal exact score totals remain server-side.
- `GET /recommendations?cursor=...&limit=...` lists the current account's recent sessions only.
- `GET /recommendations/{session_id}` returns one owned session. A valid session belonging to another account must return `404`, not reveal its existence with `403`.
- `PUT /recommendations/{session_id}/selection` stores the ordered subset selected during review. Track IDs must be unique and must belong to that session.
- Recommendation generation never writes to Spotify. The existing `create_playlist=true` shortcut is retained only on the legacy API during migration and removed when `AUTH_MODE=spotify_session` becomes final.

### Evidence Card Contract

Each recommendation item returns evidence shaped like:

```json
{
  "summary": "A melodic bridge from an artist you already return to",
  "reasons": [
    {
      "kind": "taste_anchor",
      "label": "Taste anchor",
      "detail": "Connected to one of your saved electronic artists",
      "source": "listenbrainz_co_listen",
      "strength": "strong"
    },
    {
      "kind": "prompt_match",
      "label": "Session match",
      "detail": "Lower energy and positive valence fit this session",
      "source": "reccobeats_audio",
      "strength": "moderate"
    },
    {
      "kind": "discovery",
      "label": "New to your profile",
      "detail": "Not present in the Spotify signals used for this session",
      "source": "exact_profile_membership",
      "strength": "strong"
    }
  ],
  "limitation": "Audio evidence is available, but listener-overlap evidence is sparse."
}
```

- Allowed kinds are `taste_anchor`, `discovery_bridge`, `prompt_match`, `discovery`, `diversity`, and `limitation`.
- Every statement must be generated from stored, auditable evidence. Never claim causality, emotion, personality, or certainty that the available data does not establish.
- Show qualitative strengths (`strong|moderate|limited`) based on documented thresholds. Do not expose a decimal model score as if it were a calibrated probability.
- Evidence provenance must distinguish independent data, exact user membership, and user-entered prompt data. Spotify-derived content must not be passed to an LLM to draft explanations.

### Review And Playlist Export

- `POST /recommendations/{session_id}/playlist` accepts the reviewed order and explicit playlist settings:

```json
{
  "name": "Friday Night Finds",
  "description": "Created from my Outside the Loop discovery session.",
  "public": true,
  "track_ids": ["spotify-track-id-1", "spotify-track-id-2"]
}
```

- `name` is an explicit override of the generated suggestion, trimmed and validated before Spotify is called. The frontend always sends the currently displayed name.
- Only tracks recommended in the owned session can be exported. Preserve the reviewed order, reject duplicates, require at least one track, and cap the beta playlist at 20 tracks.
- Create the playlist with `POST /me/playlists` using the current user's refreshed token, then add items with `POST /playlists/{playlist_id}/items` in bounded chunks.
- The exported playlist belongs to the Spotify account used for that application session. Return its Spotify URL and show an "Open playlist in Spotify" action.
- Require an `Idempotency-Key`. Replaying the same account/session/payload returns the recorded result; the same key with a different payload returns `409`. Persist partial failures so a retry adds only missing items and does not create duplicate playlists.
- Public and private playlists are supported. The UI defaults to private, and the user must explicitly toggle public visibility.

### Feedback, Evaluation, And History

- `POST /recommendations/{session_id}/feedback` records `like|dislike|hide_artist|save|skip` against an owned recommended item with an idempotency key.
- `hide_artist` becomes a hard account preference. `dislike` excludes the track. `like` and `save` may provide a bounded per-user reranking boost in later sessions, but five-user feedback must not train a global model.
- `POST /recommendations/{session_id}/evaluation` records `better|same|worse|not_sure` compared with the user's usual Spotify discovery, explanation usefulness `1..5`, novelty quality `1..5`, and optional short comments.
- `GET /history` returns cursor-paginated recommendation sessions and playlist status for the current user.
- Rate limits for beta default to 10 recommendation generations per user per hour, 5 profile sync requests per day, and Spotify export idempotency rather than a broad write quota. Return `429` with a retry hint.

### Spotify Policy Boundary

- Complete a phase-zero review against the current [Spotify Developer Policy](https://developer.spotify.com/policy) before invitations. Record which profile fields, transformations, storage durations, and UI uses are approved.
- Use Spotify profile signals only to fulfill the current user's requested recommendation and playlist workflow. Do not use them for advertising, cross-user profiling, model training, or unrelated analytics.
- Remove or hard-disable the production OpenAI agent orchestration path that can expose Spotify-derived tool output. If prompt parsing uses OpenAI, send only the raw user-authored prompt and receive only a bounded intent object.
- Keep Spotify artwork unmodified, attributed, and linked. Do not download it into the repository, Supabase Storage, S3, or Vercel assets.
- Present Spotify Embed as an optional preview and provide an Open Spotify link; do not build a substitute full player.

## Data Model And Persistence

### Supabase Decision

- Use Supabase Postgres for the new beta application database, accessed through the Supavisor transaction pooler with `sslmode=require`.
- Do not use Supabase Auth for Spotify sign-in. The AWS backend implements Spotify OAuth so refresh tokens never need to be handed from browser JavaScript to AWS after login.
- Do not expose `SUPABASE_URL`, `anon`, `publishable`, `service_role`, or database credentials to the frontend because the frontend has no direct database use case.
- Add `RUNTIME_STORE_BACKEND=supabase` while preserving `local` and `dynamodb` during migration. New product routes require `supabase`; legacy CLI/tests can continue using existing stores.
- Manage schema as SQL migrations in `supabase/migrations/`, validate locally with the Supabase CLI, and apply to production before deploying code that depends on a migration.

### Proposed Tables

- `app_users`
  - `account_id text primary key`
  - optional safe display fields; do not require email or legacy Spotify ID
  - `access_status text check in ('pending','approved','revoked')`
  - `refresh_token_ciphertext bytea`, `token_scopes text[]`, `token_issued_at timestamptz`
  - `reauthorization_required boolean`, `last_login_at`, `profile_synced_at`
  - `created_at`, `updated_at`, `deleted_at`, optimistic `version`
  - partial index on approved, non-deleted users for the scheduler
- `oauth_states`
  - `state_hash text primary key`, `verifier_ciphertext bytea`, validated `return_path`
  - `expires_at`, `consumed_at`, `created_at`
  - cleanup index on expiry; a transactional consume statement prevents replay
- `app_sessions`
  - `session_hash text primary key`, `account_id` foreign key with cascade
  - `csrf_hash`, `idle_expires_at`, `absolute_expires_at`, `last_seen_at`, `revoked_at`, `created_at`
  - indexes on account and expiry; never store the plaintext cookie
- `profile_sync_jobs`
  - UUID primary key, `account_id`, `status`, `requested_by`, `attempt_count`
  - redacted `error_code`, `queued_at`, `started_at`, `completed_at`
  - partial unique index allowing at most one queued/running job per account
- `taste_snapshots`
  - UUID primary key, `account_id`, monotonically increasing `snapshot_version`
  - bounded normalized `signals jsonb`, `source_counts jsonb`, `source_time_ranges text[]`
  - `synced_at`, `expires_at`, `created_at`, `normalizer_version`
  - unique `(account_id, snapshot_version)` and index for latest snapshot
  - store the minimum IDs/names required for recommendation evidence; do not store raw Spotify responses
- `user_preferences`
  - one row per account with `blocked_artist_ids text[]`, `blocked_track_ids text[]`, explicit default, and timestamps
- `recommendation_sessions`
  - UUID primary key, `account_id`, prompt, bounded `controls jsonb`, parsed intent, snapshot ID, catalog run ID, ranking version
  - `status`, `generated_at`, `updated_at`, optional reviewed playlist name/visibility
  - index `(account_id, generated_at desc)` for history
- `recommendation_items`
  - `(session_id, track_id)` primary key, original rank, internal score components, `evidence jsonb`
  - `selected boolean`, reviewed order, and immutable display/link snapshot needed to reproduce the session
  - index on session and reviewed order
- `feedback_events`
  - UUID primary key, `account_id`, `session_id`, `track_id`, constrained event type, bounded metadata, `idempotency_key`, `created_at`
  - unique `(account_id, idempotency_key)` and foreign key to the recommended item
- `playlist_exports`
  - UUID primary key, unique `session_id`, `account_id`, Spotify playlist ID/URL, name, description, public flag, ordered track IDs
  - request fingerprint, idempotency key, status, added count, redacted partial failure, timestamps
  - unique `(account_id, idempotency_key)`
- `session_evaluations`
  - unique `session_id`, `account_id`, comparison result, explanation usefulness, novelty quality, optional bounded comment, timestamps
  - foreign keys guarantee the evaluation belongs to the session owner

### Isolation, Retention, And Migrations

- Every account-owned query includes `account_id` derived from the application session. Repository methods require account context rather than accepting optional user filters.
- Enable RLS on public tables and revoke all table privileges from Supabase `anon` and `authenticated` roles. Backend-only credentials are the sole data path; RLS is defense in depth, while application ownership checks remain mandatory. See [Supabase RLS](https://supabase.com/docs/guides/database/postgres/row-level-security).
- Create foreign keys, check constraints, uniqueness constraints, and transaction boundaries in SQL rather than relying only on Pydantic validation.
- Use KMS encryption context `{purpose: spotify_refresh_token, account_id: ...}` and grant decrypt only to API/profile worker roles. Do not store the KMS plaintext or access tokens.
- Retain OAuth state for at most 24 hours after expiry, expired sessions for 7 days, and beta profile/recommendation/feedback data for 90 days unless the user deletes the account sooner. Run a daily cleanup job.
- Keep only the current and two previous taste snapshots per user after recommendation sessions no longer reference older snapshots.
- Account deletion cascades application records, revokes sessions, removes token ciphertext, and records only a non-identifying operational deletion event in CloudWatch.
- Do not dual-write DynamoDB and Supabase. Route-level feature flags select one store, avoiding inconsistent distributed writes. Leave retained DynamoDB tables untouched until a later removal plan.
- Migration rollback is forward-only: deploy a corrective SQL migration. Before destructive schema changes, take a Supabase backup and deploy code compatible with both old and new columns.

## Scientific Methodology And Beta Protocol

### Recommendation Method

1. Build the user context from exact, permitted Spotify membership/top signals and explicit first-party preferences. Do not infer demographic, personality, health, or sensitive traits.
2. Generate candidates exclusively from the independently built S3 catalog. Spotify profile tracks are anchors/known-item filters, not the discovery candidate source.
3. Exclude known tracks, blocked tracks/artists, disallowed explicit content, unavailable Spotify IDs, duplicates, and candidates lacking enough evidence to explain.
4. Score version `discovery-v1` with documented components: prompt fit 35%, independent taste bridge 30%, discovery value 20%, and independent evidence quality 15%.
5. Adjust `familiar|balanced|adventurous` by shifting at most 10 percentage points between taste bridge and discovery value; never silently change the selected mode.
6. Re-rank for artist and evidence diversity with at most one track per primary artist in a 10-track session unless coverage makes that impossible.
7. Build evidence cards directly from the highest valid component contributions and include a limitation when source coverage is sparse.
8. Version the parser, normalizer, catalog run, score weights, and evidence thresholds on every recommendation session so results are reproducible.

The proposed weights are an initial falsifiable baseline, not a claim of optimality. Before the live beta, run sensitivity checks against the five approved profiles without using their feedback to tune and evaluate the same sessions. Freeze `discovery-v1` for the first evaluation round.

### Evaluation Design

- Primary hypothesis: at least four of five testers report that the product is better than their usual Spotify discovery in a majority of their completed evaluation sessions.
- Primary session metric: proportion of `better` responses among `better|same|worse`; report `not_sure` separately.
- Tester-level guardrail: no tester should have a track acceptance rate below 20% across the prescribed sessions.
- Explanation metric: median explanation usefulness of at least 4/5 and no evidence card accuracy complaints left unresolved.
- Product metrics: selected-track rate, playlist export rate, return-session rate, exact known-track leak rate, catalog coverage, and recommendation generation latency.
- Required protocol: each tester completes at least three sessions on separate prompts: comfort-zone discovery, a mood/activity request, and an adventurous request. Prompt order is rotated across testers.
- Before first use, collect a one-question baseline about satisfaction with current discovery. After every session, capture the comparison and explanation ratings before showing aggregate results.
- Do not use five users for significance testing or broad market claims. Report counts, medians, per-user ranges, and uncertainty descriptively.
- Freeze ranking version and catalog run during the first evaluation round. Any bug fix or model change starts a new version and is analyzed separately.
- Keep qualitative comments linked to the session and ranking version. Convert repeated issues into Beads work, not silent weight changes.
- Explainable recommendation research can guide presentation and evaluation, including [user-aware explanation evaluation](https://arxiv.org/abs/2412.14193) and [explanation goals in recommender systems](https://arxiv.org/abs/1804.11192), while the implementation remains auditable and product-specific.

## Implementation Tasks

1. [ ] Establish the policy, product, and implementation baseline.
   - Files: `docs/spotify-policy-assessment.md`, `docs/product-beta-acceptance.md`, Beads implementation epic and child issues
   - Notes: Record allowed Spotify fields, storage, transformations, display attribution, AI boundary, retention, five-user quota, and a go/no-go owner. Capture the exact beta success metrics and privacy placeholders. Create a fresh implementation branch from updated `main`, claim the Beads epic, and run all existing quality gates before changes.

2. [ ] Add an architecture decision record for Vercel, AWS, and Supabase.
   - Files: `docs/decisions/0001-vercel-aws-supabase.md`, `docs/recommender-architecture.md`
   - Notes: Document why there is no CloudFront, why Supabase is database-only, why custom Spotify OAuth remains in AWS, trust boundaries, request/data flows, failure domains, and rollback to the current single-user stack.

3. [ ] Scaffold and validate the Supabase schema locally.
   - Files: `supabase/config.toml`, `supabase/migrations/<timestamp>_beta_core.sql`, `tests/integration/test_supabase_schema.py`
   - Notes: Write schema assertions first. Add enums/checks, all proposed tables, foreign keys, indexes, RLS/grants, cleanup SQL, and transaction-safe OAuth-state consumption. Do not add fake tester seed rows or committed credentials.

4. [ ] Add typed database configuration and connection lifecycle.
   - Files: `src/music_recommender/config.py`, `src/music_recommender/storage/postgres.py`, `src/music_recommender/storage/__init__.py`, `infra/lambda/api-requirements.in`, `infra/lambda/profile-sync-requirements.in`, `.env.example`, `tests/test_config.py`, `tests/test_postgres_storage.py`
   - Notes: Add `supabase` runtime mode, TLS pooler DSN, bounded pool settings, query timeout, and transaction helpers. Reuse connections across warm Lambda invocations but acquire/release per request. Redact DSNs from errors and health output. Confirm `psycopg` dependencies fit the Lambda unzipped-size limit.

5. [ ] Introduce account-scoped repository protocols and Postgres adapters.
   - Files: `src/music_recommender/storage/protocols.py`, `src/music_recommender/storage/postgres.py`, `src/music_recommender/api/services.py`, `tests/test_postgres_storage.py`, existing DynamoDB store tests
   - Notes: Define explicit repositories for users/tokens, sessions, OAuth state, snapshots/jobs, recommendations/items, feedback, exports, and evaluations. Every user-owned method requires `account_id`; ownership mismatches return no record. Keep existing DynamoDB adapters available only for legacy routes.

6. [ ] Add the KMS-backed Spotify token vault.
   - Files: `src/music_recommender/security/token_vault.py`, `src/music_recommender/security/__init__.py`, `tests/test_token_vault.py`, `infra/template.yaml`, `tests/test_infra_template.py`
   - Notes: Test encryption context, rotation replacement, access-denied handling, and redaction first. Add a customer-managed symmetric KMS key/alias with least-privilege API and worker policies. Never log token plaintext, ciphertext, authorization codes, or KMS responses.

7. [ ] Modernize and harden the Spotify client before OAuth integration.
   - Files: `src/music_recommender/sources/spotify_user.py`, `tests/test_spotify_user_client.py`
   - Notes: Add PKCE challenge/verifier support, use `POST /me/playlists` and `/playlists/{id}/items`, expose `account_id`, handle refresh-token rotation, classify `401/403/429/5xx`, honor `Retry-After`, and add bounded pagination. Keep access tokens in memory only.

8. [ ] Implement OAuth state, application sessions, CSRF, and current-user dependencies.
   - Files: `src/music_recommender/auth/models.py`, `src/music_recommender/auth/oauth.py`, `src/music_recommender/auth/sessions.py`, `src/music_recommender/api/dependencies.py`, `tests/test_oauth_service.py`, `tests/test_session_auth.py`
   - Notes: Use cryptographically random values, one-time state consumption, PKCE, hashed opaque sessions, cookie helpers, idle/absolute expiry, session rotation after OAuth, Origin checks, and double-submit CSRF. Use injectable clocks/random sources for deterministic tests.

9. [ ] Add product authentication routes and compatibility-mode middleware.
   - Files: `src/music_recommender/api/app.py`, `src/music_recommender/api/routes/auth.py`, `src/music_recommender/api/models.py`, `src/music_recommender/api/errors.py`, `tests/test_auth_api.py`, `tests/test_api_health.py`
   - Notes: Test start/callback/pending/approved/revoked/logout/delete flows before implementation. Replace global API-key assumptions with route-aware `AUTH_MODE`, secure cookie responses, stable error codes, sanitized redirects, and a shallow `/health` plus dependency-aware `/ready` that reveals no secret/config inventory.

10. [ ] Implement the deny-by-default five-user administration CLI.
    - Files: `src/music_recommender/beta_admin_cli.py`, `pyproject.toml`, `tests/test_beta_admin_cli.py`, `docs/operational-aws-runbook.md`
    - Notes: Add `pending`, `approve`, `revoke`, and `status` commands. Enforce the five-approved-user cap in one database transaction. Read credentials through existing settings/Secrets Manager patterns and print only necessary account/status information.

11. [ ] Convert profile synchronization to multi-user asynchronous jobs.
    - Files: `src/music_recommender/api/routes/profile.py`, `src/music_recommender/api/services/profile_service.py`, `src/music_recommender/api/profile_sync_handler.py`, `src/music_recommender/api/scheduled_profile_handler.py`, `tests/test_profile_sync_api.py`, `tests/test_profile_sync_worker.py`, `tests/test_scheduled_profile_handler.py`
    - Notes: Make API sync enqueue-only, implement SQS idempotency, process one user per worker invocation, isolate per-user failures, rotate token ciphertext, and write snapshot/job status transactionally. Scheduler only enqueues stale approved users. Pending/revoked users must never sync.

12. [ ] Normalize policy-bounded, account-scoped taste snapshots.
    - Files: `src/music_recommender/recommender/profile.py`, `src/music_recommender/recommender/profile_normalization.py`, `src/music_recommender/recommender/models.py`, `tests/test_profile_sync.py`, `tests/test_profile_normalization.py`
    - Notes: Remove demo-user globals and raw response persistence. Use exact source memberships and bounded source counts, preserve enough provenance for evidence, and version the normalizer. Keep recently played disabled by default and avoid synthetic sensitive traits.

13. [ ] Audit and expand the independent discovery catalog.
    - Files: `src/music_recommender/pipeline/network.py`, `src/music_recommender/recommender/catalog.py`, `src/music_recommender/recommender/data.py`, `scripts/audit_beta_catalog.py`, `tests/test_recommender_data.py`, `tests/test_catalog_coverage.py`, `docs/data-extraction.md`
    - Notes: Remove `_catalog_with_spotify_candidates` from product recommendation flow. Add a report for mapped Spotify IDs, source provenance, duplicate/known filtering, artist/genre coverage, and per-tester candidate counts without printing profile records. Require at least 1,000 eligible candidates per approved tester and enough evidence for 90% of returned tracks; rebuild the S3 run from independent data if the gate fails.

14. [ ] Replace the production intent/orchestration path with a policy-safe parser.
    - Files: `src/music_recommender/agents/intent.py`, `src/music_recommender/agents/guardrails.py`, `src/music_recommender/api/models.py`, `tests/test_agent_intent.py`, `tests/test_agent_guardrails.py`, `tests/test_agent_orchestrator.py`
    - Notes: Remove `use_openai_agent` from product requests and prevent catalog/profile tools from running in production. Default to deterministic parsing; if an LLM is configured, send only user-authored prompt text and validate a strict intent schema. Add a regression test that fails if Spotify/profile/candidate fields enter the LLM request.

15. [ ] Implement and version the discovery-first ranker.
    - Files: `src/music_recommender/recommender/scoring.py`, `src/music_recommender/recommender/models.py`, `src/music_recommender/recommender/feedback.py`, `tests/test_recommender_scoring.py`
    - Notes: Write failing tests for exact filtering, component weights, adventure adjustments, evidence-quality fallback, deterministic tie-breaking, feedback preferences, and artist diversity. Remove Spotify popularity from scoring and stop presenting total decimal scores as confidence.

16. [ ] Implement structured evidence generation and provenance validation.
    - Files: `src/music_recommender/recommender/evidence.py`, `src/music_recommender/recommender/models.py`, `src/music_recommender/api/models.py`, `tests/test_recommendation_evidence.py`
    - Notes: Generate only from auditable score components/source metadata, enforce allowed reason kinds/sources, include coverage limitations, and reject unsupported explanation claims. Snapshot evidence with the recommendation session for reproducibility.

17. [ ] Build account-scoped recommendation, selection, and history services.
    - Files: `src/music_recommender/api/services/recommendation_service.py`, `src/music_recommender/api/routes/recommendations.py`, `src/music_recommender/api/models.py`, `src/music_recommender/recommender/sessions.py`, `tests/test_recommendations_api.py`, `tests/test_recommendation_sessions.py`
    - Notes: Remove caller-selected users/runs/signals from the public contract, persist session/items transactionally, implement cursor pagination and selection ordering, and return `404` for cross-tenant IDs. Add ranking/catalog/profile versions to every response.

18. [ ] Make playlist export an explicit, current-user, idempotent action.
    - Files: `src/music_recommender/api/services/playlist_service.py`, `src/music_recommender/api/routes/playlists.py`, `src/music_recommender/recommender/playlists.py`, `tests/test_playlists_api.py`, `tests/test_spotify_user_client.py`
    - Notes: Require review, explicit name, visibility, ordered owned track IDs, and `Idempotency-Key`. Use `/me/playlists` and `/items`; persist the playlist ID before adding tracks so retries resume safely. Verify same-payload replay and different-payload conflict behavior.

19. [ ] Add account-scoped feedback, preferences, and beta evaluations.
    - Files: `src/music_recommender/api/routes/feedback.py`, `src/music_recommender/api/routes/evaluations.py`, `src/music_recommender/api/services/feedback_service.py`, `src/music_recommender/api/models.py`, `tests/test_feedback_api.py`, `tests/test_evaluations_api.py`
    - Notes: Validate event ownership/idempotency, translate hide/dislike into explicit account preferences, cap metadata/comment size, and never aggregate five-user feedback into a global ranker. Add evaluation completeness reporting for beta operations.

20. [ ] Add privacy, deletion, retention, and cleanup behavior.
    - Files: `src/music_recommender/api/services/account_service.py`, `src/music_recommender/api/cleanup_handler.py`, `infra/template.yaml`, `tests/test_account_deletion.py`, `tests/test_cleanup_handler.py`, `docs/privacy-notice.md`
    - Notes: Test cascade deletion, session/token invalidation, expired OAuth/session cleanup, snapshot retention, and failure retries. Add a daily cleanup schedule and a beta privacy notice with data categories, purpose, retention, Spotify attribution, deletion method, and contact placeholder gate.

21. [ ] Scaffold the Vercel frontend and shared API client.
    - Files: `web/package.json`, `web/package-lock.json`, `web/tsconfig.json`, `web/vite.config.ts`, `web/vercel.json`, `web/index.html`, `web/src/main.tsx`, `web/src/app/App.tsx`, `web/src/api/client.ts`, `web/src/styles/*`
    - Notes: Use React, TypeScript, Vite, React Router, TanStack Query, Zod, Lucide icons, Vitest/Testing Library/MSW, and Playwright. Calls use relative `/api`; local Vite proxies to a configurable local API. Put the external API Gateway rewrite before the SPA fallback. Do not add CloudFront or privileged `VITE_*` secrets.

22. [ ] Implement sign-in, pending access, onboarding, and auth recovery UI.
    - Files: `web/src/routes/LoginPage.tsx`, `web/src/routes/AccessPendingPage.tsx`, `web/src/routes/OnboardingPage.tsx`, `web/src/auth/AuthProvider.tsx`, `web/src/components/AppShell.tsx`, corresponding tests
    - Notes: The first screen is focused Spotify sign-in. Handle denied OAuth, expired state, pending/revoked access, profile queued/syncing/failed/reconnect states, logout, and keyboard/screen-reader behavior. Do not expose provider tokens or raw account IDs.

23. [ ] Implement the discovery composer and evidence-card results.
    - Files: `web/src/routes/DiscoverPage.tsx`, `web/src/routes/SessionPage.tsx`, `web/src/components/DiscoveryForm.tsx`, `web/src/components/RecommendationList.tsx`, `web/src/components/EvidenceCard.tsx`, corresponding tests
    - Notes: Provide prompt, segmented adventure control, explicit toggle, optional anchor, and blocked-artist management. Render loading, insufficient-profile, sparse-evidence, empty, rate-limited, and error states without layout shifts. Evidence is visible by default, concise, and expandable for provenance.

24. [ ] Integrate Spotify preview/link behavior with correct attribution.
    - Files: `web/src/components/SpotifyEmbed.tsx`, `web/src/components/TrackActions.tsx`, `web/src/lib/spotifyEmbed.ts`, corresponding tests
    - Notes: Load the Spotify iFrame API once, render only one active embed at a time, provide Open Spotify links, retain Spotify artwork aspect ratios/attribution, and provide a non-playing fallback. Verify no artwork is proxied or persisted by the app.

25. [ ] Implement review-first playlist export UI.
    - Files: `web/src/routes/ReviewPage.tsx`, `web/src/components/TrackReviewList.tsx`, `web/src/components/PlaylistExportForm.tsx`, corresponding tests
    - Notes: Support remove, accessible reorder, editable generated name, description, explicit public/private toggle, confirmation, in-flight lock, idempotent retry, partial-failure recovery, and Open Spotify success action. The frontend must never call recommendation generation with `create_playlist=true`.

26. [ ] Implement history, evaluation, settings, privacy, and deletion UI.
    - Files: `web/src/routes/HistoryPage.tsx`, `web/src/routes/SettingsPage.tsx`, `web/src/routes/PrivacyPage.tsx`, `web/src/components/SessionEvaluation.tsx`, corresponding tests
    - Notes: Add paginated session history, post-session comparison/usefulness prompts, reconnect, blocked artists, logout, and destructive account deletion confirmation. Keep operational instructions out of visible product UI.

27. [ ] Extend AWS SAM for the multi-user runtime.
    - Files: `infra/template.yaml`, `infra/README.md`, `tests/test_infra_template.py`, `infra/lambda/*.in`, generated requirements lock files
    - Notes: Add Supabase secret references, app/session settings, KMS, SQS/DLQ, profile worker, revised scheduler, cleanup schedule, scoped IAM, reserved concurrency, API throttling, logs, alarms, and outputs. Preserve existing DynamoDB resources and legacy function settings during `hybrid` rollout. Set worker timeout/memory from measured sync behavior.

28. [ ] Harden packaging and deployment scripts.
    - Files: `scripts/prepare_lambda_build.sh`, `scripts/prune_lambda_artifacts.sh`, `scripts/sync_runtime_secret.sh`, `scripts/deploy_api_sam.sh`, `scripts/smoke_test_deployed_api.sh`, `tests/test_deployment_scripts.py`
    - Notes: Add required-value validation for database/session/app URL settings without printing values, migration preflight, Supabase connectivity readiness, and new auth/profile/recommendation/export smoke phases. Fail packaging if any Parquet or CSV file exists in Lambda artifacts; report only artifact sizes and safe identifiers.

29. [ ] Add Vercel deployment configuration and environment validation.
    - Files: `web/vercel.json`, `web/.env.example`, `scripts/verify_vercel_deployment.sh`, `docs/vercel-deployment-runbook.md`, frontend tests
    - Notes: Create the Vercel project first to obtain its stable production domain, then configure the exact Spotify callback and AWS `APP_BASE_URL`. Rewrite `/api/:path*` to the current API Gateway origin and all other routes to `index.html`. Validate cookies survive the rewrite, APIs are not cached, preview OAuth is disabled, and no secret is present in the build output.

30. [ ] Add CI and credential-safe deployment automation.
    - Files: `.github/workflows/ci.yml`, `.github/workflows/deploy-aws.yml`, repository/Vercel settings documentation
    - Notes: Run Python, SQL migration, frontend, Playwright mocked-E2E, SAM, package-content, and secret-scan gates. Use GitHub OIDC to assume a scoped AWS deployment role; stop deploying with root AWS credentials. Let Vercel Git integration deploy `web/` after CI. Require manual approval for production DB migrations and AWS deployment.

31. [ ] Add product observability, audit-safe metrics, and alerting.
    - Files: `src/music_recommender/observability.py`, `infra/template.yaml`, tests, `docs/operational-aws-runbook.md`
    - Notes: Emit structured request IDs, hashed internal user correlation, route latency, recommendation coverage, sync state, Spotify status class, playlist outcome, queue age, and DLQ depth. Never log prompts with account identity, cookies, auth headers, tokens, raw Spotify payloads, or comments. Alarm on API/worker errors, latency, database failures, reconnect spikes, and DLQ messages.

32. [ ] Update API, deployment, architecture, privacy, and methodology runbooks.
    - Files: `README.md`, `docs/api-usage-runbook.md`, `docs/aws-deployment-architecture-runbook.md`, `docs/operational-aws-runbook.md`, `docs/recommender-methodology-runbook.md`, `docs/vercel-deployment-runbook.md`
    - Notes: Include exact curl/Postman examples using browser sessions where practical, OAuth flow, explicit playlist name/public payload, user ownership guarantees, Supabase migration/recovery, Vercel rewrite, no-CloudFront rationale, five-user approval, token reconnect, data deletion, scientific protocol, rollback, and secret-redaction rules.

33. [ ] Validate locally with unit, integration, contract, UI, security, and package tests.
    - Files: all changed code/tests and generated build artifacts outside git
    - Notes: Start local Supabase, reset migrations, run the complete Python and frontend suites, mock Spotify failure/retry paths, run cross-tenant/security tests, build SAM and Vercel artifacts, and prove no credentials, Parquet, or CSV files are included. Resolve every failure before deployment.

34. [ ] Provision Supabase and deploy AWS in compatibility mode.
    - Files: production Supabase project, AWS Secrets Manager/KMS/SQS/Lambda/API Gateway/CloudWatch resources
    - Notes: Create the project in the selected region, enable backups, apply migrations, create least-privilege pooler credentials, update Secrets Manager, deploy `AUTH_MODE=hybrid`, verify stack outputs/alarms/DLQ, and run database/API readiness without printing credentials. Keep legacy API-key smoke behavior available during rollback window.

35. [ ] Deploy the Vercel production frontend and complete Spotify configuration.
    - Files: Vercel project/settings and Spotify developer dashboard configuration
    - Notes: Deploy once for the stable URL, register its exact `/api/auth/spotify/callback`, configure the AWS app URL, deploy the final rewrite-enabled frontend, and add the five testers to Spotify's dashboard when identities are supplied. Verify CSP, cookies, deep links, attribution, and mobile/desktop layout against production.

36. [ ] Run live multi-user end-to-end acceptance and switch auth mode.
    - Files: deployed Vercel/AWS/Supabase/Spotify resources and redacted smoke evidence
    - Notes: Test owner plus at least one second allowlisted account before all five: pending login, approval, profile sync, account-isolated recommendation, evidence, review/reorder, custom public and private playlist names, Spotify visibility in the correct accounts, feedback, evaluation, history, logout, reconnect simulation, and deletion. Prove cross-account session IDs cannot be read or exported. Switch to `AUTH_MODE=spotify_session` only after these pass.

37. [ ] Execute the frozen five-tester beta and produce the decision report.
    - Files: `docs/beta-results/<date>-discovery-v1.md`, Beads findings/issues
    - Notes: Run the prescribed three-session protocol, export aggregate/non-identifying metrics, summarize per-user ranges and comments, compare against success thresholds, and create Beads issues for evidence errors or quality gaps. Do not change ranking weights during the frozen round.

38. [ ] Complete release review, rollback rehearsal, documentation, and push.
    - Files: plan completion evidence, runbooks, Beads issue state, git history
    - Notes: Perform security/policy/accessibility review, restore the previous API configuration in a non-production rehearsal, verify database backup recovery steps, close completed Beads issues, file unresolved follow-ups, commit cohesive changes, pull/rebase, push, and verify the branch is up to date with origin.

## Tests And Scenarios

- Unit tests: PKCE/state construction; one-time state consumption; cookie/session expiry; CSRF/Origin checks; KMS context and redaction; Spotify token rotation and 2026 endpoints; profile normalization; deterministic ranking components; evidence provenance; idempotency fingerprints; access-status transitions; rate-limit counters; account deletion.
- Database integration tests: migrations from empty database; constraints; at-most-five approval transaction; OAuth replay race; one active sync job; session hash lookup; recommendation/item transaction rollback; cross-account ownership; feedback/export idempotency; cascade deletion; cleanup retention; connection recovery.
- API contract tests: all auth/profile/recommendation/selection/playlist/feedback/evaluation/history endpoints; stable status/error codes; no user ID override; no token/config leakage; cursor validation; body size limits; `404` for foreign resources; legacy compatibility only under `api_key|hybrid`.
- Spotify integration tests with fakes: consent denied, callback mismatch, missing scope, missing `account_id`, refresh rotation, six-month reconnect, `401`, `403`, `429 Retry-After`, transient `5xx`, paginated profile data, public/private create via `/me/playlists`, `/items` chunking, partial add recovery, idempotent replay.
- Recommender tests: known/blocked/explicit filtering, no Spotify popularity, no profile tracks added as candidates, minimum evidence, adventure weight shift, deterministic ties, one artist cap, sparse catalog fallback, first-party feedback boundaries, ranking version capture, no LLM exposure of Spotify/candidate/profile data.
- Frontend component tests: auth bootstrap, pending/reconnect states, discovery control validation, loading/empty/errors, evidence expansion, one active embed, accessible reordering, playlist name override, visibility toggle, idempotent retry, history, survey, privacy, and deletion confirmation.
- Playwright mocked E2E: login callback simulation; queued profile to ready; recommendation to evidence to review to named playlist; partial export retry; second-user isolation; expired session; mobile navigation at 375x812; tablet and 1440px desktop; keyboard-only and screen-reader labels.
- Live E2E: exact Vercel callback; same-origin API rewrite; secure cookies; pending then approval; two real Spotify users; separate profile snapshots; playlist appears only in the initiating account; custom name and public/private state match; Spotify links/attribution work; no browser request reaches Supabase.
- Security tests: OAuth state replay, open redirect, session fixation, CSRF, forged Origin, cookie theft replay after logout, SQL injection, horizontal access attempts, idempotency-key collision, log capture scan, secrets/build scan, dependency audit, API throttling.
- Operational tests: EventBridge enqueues only stale approved users; SQS retries and DLQ alarm; one user failure does not block others; database outage returns safe errors; KMS denial fails closed; Supabase backup exists; API and worker alarms transition under controlled failure; rollback restores the legacy path.
- Packaging tests: Lambda artifacts stay under AWS limits and contain no `.parquet`, `.csv`, `.env`, token fixture, frontend source map with secrets, test cache, or local Supabase state.
- Beta methodology tests: every completed session records ranking/catalog/profile versions; each tester completes three prompt categories; evaluation cannot reference another user's session; aggregate reports suppress direct account identifiers; ranking stays frozen during round one.
- Regression scenarios: local CLI and pipeline tests continue passing; private S3 access remains unchanged; legacy single-user API functions in compatibility mode; existing DynamoDB tables are retained; no live playlist is created during recommendation generation alone.

## Validation Commands

```bash
bd prime
bd show <implementation-issue-id>
uv sync --all-groups
uv run ruff format --check src tests
uv run ruff check src tests
uv run mypy src tests
uv run pytest

supabase start
supabase db reset
supabase db lint --local
uv run pytest tests/integration/test_supabase_schema.py

npm --prefix web ci
npm --prefix web run lint
npm --prefix web run typecheck
npm --prefix web run test -- --run
npm --prefix web run build
npm --prefix web run test:e2e

bash -n scripts/prepare_lambda_build.sh
bash -n scripts/prune_lambda_artifacts.sh
bash -n scripts/sync_runtime_secret.sh
bash -n scripts/deploy_api_sam.sh
bash -n scripts/smoke_test_deployed_api.sh
bash -n scripts/verify_vercel_deployment.sh
sam validate --lint --template-file infra/template.yaml
sam build --template-file infra/template.yaml
find .aws-sam/build -type f \( -name '*.parquet' -o -name '*.csv' \) -print
du -sk .aws-sam/build/*

aws sts get-caller-identity
aws cloudformation describe-stacks --stack-name music-recommender-demo --region us-east-1
aws sqs get-queue-attributes --queue-url <profile-sync-dlq-url> --attribute-names ApproximateNumberOfMessages
aws cloudwatch describe-alarms --alarm-name-prefix music-recommender --region us-east-1

vercel pull --yes --environment=production --cwd web
vercel build --prod --cwd web
vercel deploy --prebuilt --prod --cwd web
bash scripts/verify_vercel_deployment.sh <vercel-production-url>

STACK_NAME=music-recommender-demo AWS_REGION_VALUE=us-east-1 bash scripts/smoke_test_deployed_api.sh
git status --short --branch
```

- `find` must print no Parquet or CSV paths. Turn that assertion into a deployment-script failure rather than relying on manual inspection.
- Commands that read Secrets Manager or database credentials must keep values in process memory/stdin and suppress payload output. Never put a secret literal in shell history or this plan.
- The live smoke command must print only safe status, counts, session IDs, playlist IDs/URLs, and redacted user aliases.

## Deployment Sequence And Acceptance Gates

1. Policy gate: approve Spotify data use, attribution, AI boundary, privacy copy, and five-user Development Mode constraints.
2. Local gate: all Python, Supabase, frontend, Playwright, SAM, security, and package-content checks pass.
3. Database gate: production Supabase project has backups, migrations, least-privilege credentials, TLS connectivity, and no public table grants.
4. AWS identity gate: deployment uses a scoped IAM/OIDC role, not account-root access keys.
5. Vercel bootstrap gate: deploy a non-OAuth shell to obtain the stable production domain.
6. Spotify configuration gate: register the exact Vercel callback and configure only the required scopes/testers.
7. AWS compatibility gate: deploy database/KMS/SQS/workers/new routes under `AUTH_MODE=hybrid`; legacy API remains reversible.
8. Vercel product gate: deploy the final frontend/rewrite and verify secure same-origin session behavior.
9. Two-user gate: owner and one second tester pass identity isolation, sync, recommendation, evidence, named public/private playlist, feedback, history, and deletion tests.
10. Five-user gate: add/approve only the final five accounts, verify queue/catalog coverage, then switch to `AUTH_MODE=spotify_session`.
11. Beta gate: freeze `discovery-v1`, run the three-session protocol, produce the report, and decide whether quality merits another iteration.

## Risks And Rollback

- Risk: Spotify policy may prohibit part of the planned profile analysis or persistence.
  Mitigation: Make policy review the first release gate, minimize fields/retention, keep ranking local, and never train AI on Spotify data.
  Rollback: Keep invitations disabled, remove disallowed fields/transformations in a forward migration, and operate only the policy-approved subset or pause the beta.
- Risk: Spotify Development Mode or 2026 API behavior changes again.
  Mitigation: Pin current endpoint contract tests, monitor official change logs, use `account_id`, and keep OAuth/scopes isolated behind the Spotify client.
  Rollback: Disable login/export with a maintenance flag while preserving sessions/history; reauthorize users after client changes.
- Risk: Supabase introduces a second cloud dependency and database/network outages.
  Mitigation: Use transaction pooling, strict timeouts, health checks, backups, bounded retries, and AWS alarms on database error classes.
  Rollback: Switch `AUTH_MODE` back to `api_key` for the legacy demo. Do not attempt unsafe runtime dual-write; restore Supabase from backup for product data.
- Risk: A database credential could bypass tenant controls.
  Mitigation: Keep it backend-only in Secrets Manager, use a least-privilege role, revoke public grants, require account-scoped repositories, and test horizontal access on every route.
  Rollback: Rotate the database credential immediately, revoke sessions, audit access logs, and notify/delete affected beta data as required.
- Risk: Refresh-token or session leakage would permit account actions.
  Mitigation: KMS encryption context, hashed sessions, HttpOnly/Secure cookies, CSRF/Origin checks, no secret logs, short idle lifetime, and reconnect/revocation workflows.
  Rollback: Revoke all sessions, remove ciphertext, rotate Spotify client secret if needed, and require every affected user to reconnect.
- Risk: Vercel external rewrites do not preserve callback cookies/headers as expected.
  Mitigation: Add a production rewrite smoke test before inviting users and derive redirects from configured `APP_BASE_URL`, never forwarded Host alone.
  Rollback: Temporarily use a direct API callback plus tightly scoped CORS/SameSite configuration, or fix the rewrite before enabling OAuth; do not add CloudFront as an untested workaround.
- Risk: The independent catalog has insufficient coverage for five distinct profiles.
  Mitigation: Add per-user candidate/evidence gates and rebuild from broader ListenBrainz/ReccoBeats inputs before the frozen beta.
  Rollback: Show an honest insufficient-coverage state and collect missing anchor genres; do not fill results with known profile tracks or unsupported evidence.
- Risk: Five-user feedback is noisy and easy to overfit.
  Mitigation: Freeze one ranking version, prescribe prompt categories, report per-user outcomes, and treat results as directional.
  Rollback: Do not claim superiority; use findings only to choose the next hypothesis and beta iteration.
- Risk: Playlist export creates visible side effects or duplicates.
  Mitigation: Require review/confirmation, explicit account/name/visibility display, idempotency keys, persisted playlist IDs, and partial-add recovery.
  Rollback: Link the created playlist for user deletion, stop retrying completed creation, and remove the export record only after an operator confirms state.
- Risk: Added Postgres/KMS dependencies push Lambda past package limits.
  Mitigation: Measure every build, prune tests/caches/data, keep Parquet/CSV in S3 only, and consider a Lambda layer or separate thin API package if headroom drops below 10%.
  Rollback: Revert the package dependency change or split the worker/API package before production; never deploy an oversized or data-bearing artifact.
- Risk: Existing AWS CLI access uses root credentials.
  Mitigation: Require IAM Identity Center or GitHub OIDC/scoped deployment role before the product deployment.
  Rollback: Revoke root access keys after the scoped identity works and audit CloudTrail for the deployment window.
- Risk: A failed schema migration breaks the API.
  Mitigation: Apply backward-compatible migrations before code, back up first, and use expand/migrate/contract sequencing.
  Rollback: Redeploy the prior API version and apply a forward corrective migration or restore the pre-migration backup into a replacement project.

## Handoff Notes

- The durable planning issue is `music-recommender-3cy`. Before implementation, create a Beads epic and phase-sized child issues; use Beads, not this document, as the execution status source of truth.
- Execute this plan with the `implement-from-plan` workflow: create a new branch from latest `main`, write failing tests before behavior, make minimal changes, and keep issue status current.
- The architecture decision is explicit: Vercel frontend, AWS API/workers/S3/KMS/Secrets/observability, Supabase Postgres, custom AWS Spotify OAuth, and no CloudFront.
- Supabase Auth is deliberately excluded because Spotify provider refresh-token lifecycle still requires application handling. Revisit only if an SSR callback design can prove equivalent token custody with less complexity.
- Do not expose or print the existing API key, Spotify client secret, refresh tokens, session cookies, Supabase DSN, KMS plaintext, or OAuth codes. Test fixtures must use obvious fake values.
- Never accept user/account identity from a recommendation or playlist request. The authenticated session is the only ownership source.
- Playlist creation is review-first. Recommendation generation must have no Spotify write side effect in the final product mode.
- The playlist name in the export request overrides the generated suggestion, and the exported playlist must appear in the Spotify account that completed OAuth for that session.
- Keep Vercel preview deployments useful with mocked/local APIs, but only the stable production domain participates in live Spotify OAuth.
- Do not package Parquet or CSV files in Lambda/Vercel artifacts. Private S3 catalog objects remain runtime data and should not be copied into build directories.
- Do not delete retained DynamoDB tables, remove legacy runbooks, or disable the live API until the two-user production gate and rollback rehearsal pass.
- Complete the five-user identity list, privacy contact, Supabase project, and Spotify policy signoff before sending tester invitations; none is a reason to weaken the deny-by-default code path.
