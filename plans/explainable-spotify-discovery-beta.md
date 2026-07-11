# Explainable Spotify Discovery Beta

## Source Request

Turn the existing single-user AWS music recommender into a product-first beta for five Spotify users. Each tester signs in with Spotify, explicitly selects artist or recording seeds, receives recommendations generated from automated MusicBrainz and ListenBrainz APIs, understands each result through evidence cards, reviews and reorders tracks, explicitly names the playlist, and creates that playlist in their own Spotify account. Deploy the frontend on Vercel, retain the Python backend on AWS, use Supabase for product persistence and API caching, leave the internal beta allowlist configurable until the five testers are known, and do not use CloudFront, local catalog files, or S3 data in the product runtime.

## Goals

- Deliver a mobile-responsive web application whose first screen is the actual Spotify sign-in and discovery workflow, not a marketing landing page.
- Support exactly five Spotify Development Mode testers for the initial beta, with a deny-by-default internal approval workflow in addition to Spotify's dashboard allowlist.
- Replace the shared API-key product experience with per-user Spotify OAuth, opaque application sessions, CSRF protection, and strict tenant isolation.
- Let each approved user explicitly select one to five MusicBrainz-backed artist or recording seeds without reading Spotify listening/profile data.
- Produce 10-track discovery sessions through automated MusicBrainz and ListenBrainz API calls, with normalized cache state in Supabase and no local/S3 catalog dependency.
- Explain every recommendation with deterministic evidence cards that identify the selected seed, independent discovery bridge, prompt match, evidence source, and confidence limitation.
- Make recommendation review mandatory before Spotify side effects. Users can remove and reorder tracks, override the generated playlist name, choose public or private visibility, and then explicitly export.
- Ensure playlist export uses the logged-in user's token and Spotify's current `/me/playlists` and playlist `/items` APIs so the playlist appears in that same user's Spotify library.
- Persist multi-user identity, sessions, explicit seeds, normalized external API caches, recommendation history, feedback, playlist exports, and beta evaluations in Supabase Postgres.
- Keep Spotify OAuth/token custody and all privileged database access in the AWS backend. Store refresh tokens only as AWS KMS ciphertext.
- Deploy the Vite frontend through Vercel and proxy same-origin `/api/*` requests to AWS API Gateway using a Vercel external rewrite. CloudFront is not required.
- Operate external-source discovery jobs asynchronously, with source-aware throttling, retries, dead-letter handling, monitoring, redacted logs, cache cleanup, account deletion, and a documented Spotify reconnect flow.
- Run a structured five-tester beta that measures whether recommendations are perceived as better than the testers' usual Spotify discovery experience and whether explanations are useful.

## Non-Goals

- Monetization, subscriptions, billing, advertising, or a public launch.
- More than five Spotify Development Mode users or an Extended Quota Mode application during this phase.
- A native iOS/Android app, background playback, a full music player, or replacement of Spotify's core listening experience.
- CloudFront, S3 website hosting, Route 53, or a custom domain for the first beta. Vercel's stable production domain is sufficient.
- Supabase Auth. It does not manage or persist Spotify provider refresh-token rotation, so it does not remove the need for trusted backend token custody.
- Direct browser access to Supabase, exposure of a Supabase service key, or using Supabase row-level security as the primary application authentication mechanism.
- Reading Spotify top, saved, recent, followed, or playlist content for recommendations; training or fine-tuning an ML/AI model on Spotify Content; or building cross-user behavioral profiles.
- Migrating historical single-user DynamoDB demo records into the beta database. The existing deployment remains available temporarily for rollback and comparison.
- Real-time collaborative playlists, social feeds, following other users, notifications, or administrator UI.
- Statistical claims of product superiority based on five users. The beta produces directional product evidence, not a generalizable scientific conclusion.
- Using local files, S3 objects, Parquet, CSV, or repository seed datasets in the product recommendation runtime. Existing S3/DynamoDB resources remain legacy-only during rollback.

## Assumptions

- The beta product direction is the previously agreed explainable new-music discovery experience, provisionally named "Outside the Loop". The final brand can change without changing the architecture.
- The frontend will be a new React, TypeScript, and Vite application under `web/`. This keeps the static frontend deployable on Vercel and independent of the existing Python package.
- Vercel serves the frontend and already provides CDN/edge delivery. A rewrite from `/api/:path*` to API Gateway gives the browser a same-origin application surface, so CloudFront adds no required capability for this beta. See [Vercel external rewrites](https://vercel.com/docs/routing/rewrites).
- AWS account `571600852509`, region `us-east-1`, API stack `music-recommender-demo`, and the currently deployed API are the starting environment. Existing S3 resources are legacy-only; product code must not depend on them.
- Supabase Postgres is selected for new product state because the beta requires relational user ownership, history, idempotency, surveys, cleanup, and cross-record integrity. Supabase Auth is intentionally not selected because [provider token refresh is application-managed and provider tokens are not stored by Supabase Auth](https://supabase.com/docs/guides/auth/social-login).
- The AWS API will connect to Supabase's transaction-mode pooler using TLS and backend-only credentials stored in AWS Secrets Manager. No database credential or privileged key is emitted into Vite environment variables.
- The stable Vercel production URL will be registered as the one Spotify redirect URI for the beta. Spotify requires an exact HTTPS redirect match; preview URLs will not run live OAuth. See [Spotify redirect URI requirements](https://developer.spotify.com/documentation/web-api/concepts/redirect_uri).
- Spotify Development Mode currently supports up to five allowlisted users and requires the app owner to have Premium. This beta remains within that boundary. See [Spotify quota modes](https://developer.spotify.com/documentation/web-api/concepts/quota-modes).
- The five tester identities are not known yet. First-time OAuth users will be recorded as `pending`; only a backend CLI can mark them `approved`. There will be no wildcard or permissive placeholder allowlist.
- `account_id`, introduced for the 2026 Development Mode migration, is the durable Spotify account key. Display name, image, email, and legacy user ID are optional and must not be identity dependencies. See the [May 2026 change note](https://developer.spotify.com/documentation/web-api/references/changes/may-2026).
- Product Spotify scopes are limited to account identity requirements and `playlist-modify-private`/`playlist-modify-public`. Product routes must not request top, library, recent, or playlist-read scopes.
- The production recommender is deterministic. An LLM may parse only the user's own free-text prompt into a bounded intent schema; it must never receive Spotify content, external candidate metadata, account data, or recommendation results.
- MusicBrainz resolves explicit user seeds and canonical metadata. ListenBrainz artist/tag radio and optional Labs similarity generate independent candidates. Supabase is the only persistent catalog/cache.
- ReccoBeats is disabled for product routes because its current terms identify Spotify-derived foundational metadata. It can be reconsidered only through a separate policy decision.
- Spotify metadata/artwork displayed by the UI will retain Spotify attribution and link back to Spotify, and playback will use the official Spotify Embed or an "Open in Spotify" action. See [Spotify design requirements](https://developer.spotify.com/documentation/design) and [Spotify Embed](https://developer.spotify.com/documentation/embeds/tutorials/using-the-iframe-api).
- The existing single-user API and DynamoDB tables can remain live under a compatibility flag until the multi-user deployment passes production smoke tests. No destructive table deletion is part of this plan.

## Open Questions

- Which five Spotify accounts will be added to the Spotify dashboard and approved internally? This does not block implementation because users can remain `pending` until account IDs are known.
- Product identity is confirmed as `Outside the Loop`, with Vercel project slug `outside-the-loop-beta`.
- Which Supabase organization, project reference, database region, and billing owner should be used? Prefer a US East region close to the AWS deployment.
- What public privacy contact and data-controller name should appear in the beta privacy notice? Use explicit placeholders that fail the production readiness check until replaced.
- Does the Spotify developer application owner currently satisfy the Premium and Development Mode requirements? Validate before inviting testers.
- The engineering policy assessment approved the explicit-input design and rejected Spotify profile analysis. Any future Spotify profile-data use requires a new policy decision.

## Current Repo Context

- The repository is a Python 3.12 package using FastAPI, Mangum, AWS SAM, S3, DynamoDB, and scheduled Lambda functions. There is no frontend or Node workspace today.
- `src/music_recommender/api/app.py` applies one optional `X-API-Key` to every protected route. That is suitable for the existing private demo but cannot identify or isolate five end users.
- `src/music_recommender/api/services.py` contains a single legacy `DemoApiService`. It reads one cached profile, accepts caller-controlled `demo_user_id` and run IDs, appends Spotify profile tracks into the candidate catalog, persists to DynamoDB/JSON, and can create a playlist during recommendation generation. Product routes must not reuse those profile/catalog paths.
- `src/music_recommender/config.py` contains one `SPOTIFY_USER_REFRESH_TOKEN`, one `SPOTIFY_DEMO_USER_ID`, four DynamoDB table names, and `RUNTIME_STORE_BACKEND=auto|local|dynamodb`. It has no app base URL, session, KMS, queue, or Supabase settings.
- `src/music_recommender/sources/spotify_user.py` already supports authorization-code exchange, refresh, current-user profile, top items, saved tracks, playlists, and playlist reads. Playlist writes still call removed/deprecated paths: `POST /users/{id}/playlists` and `POST /playlists/{id}/tracks`. They must become `POST /me/playlists` and `POST /playlists/{id}/items` per Spotify's [February 2026 migration guide](https://developer.spotify.com/documentation/web-api/tutorials/february-2026-migration-guide).
- `src/music_recommender/recommender/scoring.py` currently weights mood 65%, direct taste 20%, novelty 5%, and popularity 10%, then emits a score in explanation text. This does not prioritize discovery, uses pseudo-precise user-facing scores, and does not expose evidence provenance.
- `src/music_recommender/agents/orchestrator.py` and `src/music_recommender/agents/tools.py` can send catalog/profile-derived data through OpenAI tool calls when `use_openai_agent=true`. That production path conflicts with the intended Spotify data boundary and must be disabled before beta use.
- `src/music_recommender/recommender/profile.py` normalizes a single user's Spotify data into affinities and candidates. It remains legacy-only; the product needs explicit seed models and independent API candidate records.
- `src/music_recommender/storage/dynamodb.py` implements users, sessions, feedback, and playlist stores with keys designed around one demo user/session. The interfaces are reusable, but the new product persistence needs account ownership and relational constraints.
- `infra/template.yaml` defines one API Lambda, one scheduled profile Lambda, four retained DynamoDB tables, API access logs, alarms, S3 access, and runtime secret references. Product infrastructure needs KMS, discovery SQS/DLQ, Supabase settings, external API configuration, new IAM grants, and cache cleanup while preserving legacy resources.
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
                      -> Spotify Web API (identity/playlist writes only)
                      -> Supabase Postgres transaction pooler
                      -> MusicBrainz Web Service
                      -> ListenBrainz API and Labs
                      -> AWS KMS (refresh-token encrypt/decrypt)
                      -> SQS discovery queue
                 -> discovery worker Lambda
                      -> MusicBrainz/ListenBrainz
                      -> Supabase Postgres
                 -> EventBridge cache-cleanup Lambda
                      -> Supabase expired-cache query

CloudWatch logs/metrics/alarms observe API, scheduler, worker, queue, and DLQ.
Secrets Manager holds Spotify, database, session, and optional prompt-parser secrets.
```

- Vercel is the public web edge. Do not add CloudFront in front of Vercel or API Gateway.
- The browser calls relative `/api` URLs. Production CORS is therefore not part of normal request flow; only explicit localhost origins are allowed for local development.
- AWS is the only trusted application backend. It owns OAuth state, session issuance, Spotify token refresh, authorization, recommendations, persistence access, and side effects.
- Supabase is a managed Postgres provider, not a second application backend. The browser does not use Supabase Auth or Data APIs.
- Product routes never read local or S3 catalog data. Existing S3 objects stay private and legacy-only during rollback.

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
  - Redirect pending users to `/access-pending`; redirect approved users to seed onboarding or discovery.
- `GET /auth/me`
  - Return only application identity, access status, seed readiness, reauthorization status, and safe display fields. Never return Spotify or database tokens.
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

### Explicit Seeds And Automated Discovery

- `GET /music/search?q=...&type=artist|recording` searches MusicBrainz through a server-side client and returns bounded canonical choices; it never proxies arbitrary query syntax.
- `PUT /me/seeds` stores one to five explicitly confirmed MusicBrainz artist/recording MBIDs for the current account.
- `GET /me/seeds` returns only the current account's selected seeds and source labels.
- `POST /discovery/jobs` enqueues idempotent MusicBrainz/ListenBrainz expansion for stale or missing seed data and returns `202` with `job_id`.
- `GET /discovery/jobs/{job_id}` returns `queued|running|ready|degraded|failed` plus safe source coverage and a redacted error code.
- MusicBrainz calls use a contactable `User-Agent`, a distributed one-request-per-second limiter, strict timeouts, and Supabase caching.
- ListenBrainz calls honor `X-RateLimit-*`, `Retry-After`, `429`, bounded `5xx` retries, and source-specific TTLs.
- Artist seeds use core LB Radio; recording similarity is experimental and feature-flagged with artist-radio fallback.
- A cleanup job removes expired cache rows. No scheduler fetches Spotify profile data.
- Spotify refresh tokens can expire or rotate only for identity/export. Persist replacement ciphertext atomically and provide a reconnect action. See [Spotify refresh tokens](https://developer.spotify.com/documentation/web-api/tutorials/refreshing-tokens).

### Recommendation Contract

- `POST /recommendations` accepts:

```json
{
  "prompt": "Warm electronic music for a late-night walk",
  "limit": 10,
  "adventure": "balanced",
  "allow_explicit": false,
  "blocked_artist_ids": [],
  "seed_ids": ["musicbrainz-mbid"]
}
```

- Public requests no longer accept `create_playlist`, `playlist_name`, `playlist_public`, `use_openai_agent`, catalog run IDs, interaction run IDs, liked IDs, known IDs, Spotify profile data, or user IDs.
- The service validates owned explicit seeds, loads fresh Supabase candidate caches, and enqueues missing expansion. It returns `202 discovery_queued` while required source data is unavailable.
- Response items include Spotify track link/embed identifiers, display metadata, rank, and a structured evidence card. Internal exact score totals remain server-side.
- `GET /recommendations?cursor=...&limit=...` lists the current account's recent sessions only.
- `GET /recommendations/{session_id}` returns one owned session. A valid session belonging to another account must return `404`, not reveal its existence with `403`.
- `PUT /recommendations/{session_id}/selection` stores the ordered subset selected during review. Track IDs must be unique and must belong to that session.
- Recommendation generation never writes to Spotify. The existing `create_playlist=true` shortcut is retained only on the legacy API during migration and removed when `AUTH_MODE=spotify_session` becomes final.

### Evidence Card Contract

Each recommendation item returns evidence shaped like:

```json
{
  "summary": "A listener-supported bridge from your selected seed",
  "reasons": [
    {
      "kind": "seed_bridge",
      "label": "Selected seed",
      "detail": "Connected to the artist seed you selected for this session",
      "source": "listenbrainz_artist_radio",
      "strength": "strong"
    },
    {
      "kind": "prompt_match",
      "label": "Session match",
      "detail": "Independent tags overlap with the session prompt",
      "source": "listenbrainz_tags",
      "strength": "moderate"
    },
    {
      "kind": "source_support",
      "label": "Source support",
      "detail": "Supported by multiple independent listener paths",
      "source": "listenbrainz_similarity",
      "strength": "moderate"
    }
  ],
  "limitation": "Tag evidence is available, but recording-level similarity is experimental."
}
```

- Allowed kinds are `seed_bridge`, `prompt_match`, `source_support`, `diversity`, and `limitation`.
- Every statement must be generated from stored, auditable evidence. Never claim causality, emotion, personality, or certainty that the available data does not establish.
- Show qualitative strengths (`strong|moderate|limited`) based on documented thresholds. Do not expose a decimal model score as if it were a calibrated probability.
- Evidence provenance must distinguish explicit user input, MusicBrainz facts, ListenBrainz facts, and experimental source data. Spotify-derived content must not be passed to an LLM or used in ranking.

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
- Rate limits for beta default to 10 recommendation generations and 20 seed searches per user per hour, with source-level MusicBrainz/ListenBrainz throttles and Spotify export idempotency. Return `429` with a retry hint.

### Spotify Policy Boundary

- Enforce the accepted `docs/spotify-policy-assessment.md`: Spotify is limited to application identity, attributed links/display, and explicit playlist export.
- Product routes must not request or call Spotify top, library, recently played, followed, or playlist-read APIs and must not derive ranking features from Spotify content.
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
  - `reauthorization_required boolean`, `last_login_at`
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
- `user_seeds`
  - UUID primary key, `account_id`, `entity_type check in ('artist','recording')`, canonical MusicBrainz MBID
  - confirmed display label, position, selected timestamp, and optional removal timestamp
  - unique active `(account_id, entity_type, mbid)` and a database trigger enforcing one to five active seeds
- `discovery_jobs`
  - UUID primary key, `account_id`, request fingerprint, status, requested source adapters, attempt count
  - redacted `error_code`, `queued_at`, `started_at`, `completed_at`
  - partial unique index allowing at most one equivalent queued/running job per account
- `music_entities`
  - canonical MusicBrainz MBID primary key, entity type, normalized name/credits/release data, source timestamps and expiry
  - no Spotify metadata or raw source response
- `candidate_edges`
  - source seed MBID, candidate recording MBID, source adapter, algorithm/version, independent strength/listener support
  - fetched and expiry timestamps; unique source/seed/candidate/algorithm tuple
- `external_id_mappings`
  - MusicBrainz recording MBID, provider, provider ID, mapping source/confidence, fetched/expiry timestamps
  - Spotify mappings are used only after ranking for link/export and expire within 24 hours
- `source_cache_entries`
  - source, normalized cache key, bounded normalized payload, status, ETag if supplied, fetched/expiry timestamps
  - positive and negative TTLs; no raw Spotify response
- `user_preferences`
  - one row per account with `blocked_artist_ids text[]`, `blocked_track_ids text[]`, explicit default, and timestamps
- `recommendation_sessions`
  - UUID primary key, `account_id`, prompt, bounded `controls jsonb`, parsed intent, ordered seed IDs, source snapshot/version, ranking version
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
- Use KMS encryption context `{purpose: spotify_refresh_token, account_id: ...}` and grant decrypt only to API/export roles. Do not store the KMS plaintext or access tokens.
- Retain OAuth state for at most 24 hours after expiry, expired sessions for 7 days, and beta seed/recommendation/feedback data for 90 days unless the user deletes the account sooner. Run a daily cleanup job.
- Enforce source-specific cache TTLs and retain immutable evidence facts referenced by a recommendation session until that session expires.
- Account deletion cascades application records, revokes sessions, removes token ciphertext, and records only a non-identifying operational deletion event in CloudWatch.
- Do not dual-write DynamoDB and Supabase. Route-level feature flags select one store, avoiding inconsistent distributed writes. Leave retained DynamoDB tables untouched until a later removal plan.
- Migration rollback is forward-only: deploy a corrective SQL migration. Before destructive schema changes, take a Supabase backup and deploy code compatible with both old and new columns.

## Scientific Methodology And Beta Protocol

### Recommendation Method

1. Build the session context from explicitly selected MusicBrainz seeds, user-entered prompt/controls, and first-party product feedback. Do not infer demographic, personality, health, or sensitive traits.
2. Generate candidates through automated MusicBrainz and ListenBrainz APIs, using only fresh normalized Supabase cache records. Do not read local/S3 catalogs.
3. Exclude seed recordings, blocked tracks/artists, disallowed explicit content when independently established, unavailable export mappings, duplicates, and candidates lacking enough evidence to explain.
4. Score version `explicit-discovery-v1` with documented components: prompt/tag fit 35%, independent seed bridge 30%, discovery value 20%, and evidence quality 15%.
5. Adjust `familiar|balanced|adventurous` by shifting at most 10 percentage points between seed bridge and discovery value; never silently change the selected mode.
6. Re-rank for artist and evidence diversity with at most one track per primary artist in a 10-track session unless coverage makes that impossible.
7. Build evidence cards directly from the highest valid component contributions and include a limitation when source coverage is sparse.
8. Version the parser, source adapters/algorithms, source fetch timestamps, score weights, and evidence thresholds on every recommendation session so results are reproducible.

The proposed weights are an initial falsifiable baseline, not a claim of optimality. Before the live beta, run sensitivity checks with a fixed explicit-seed scenario set without using tester feedback to tune and evaluate the same sessions. Freeze `explicit-discovery-v1` for the first evaluation round.

### Evaluation Design

- Primary hypothesis: at least four of five testers report that the product is better than their usual Spotify discovery in a majority of their completed evaluation sessions.
- Primary session metric: proportion of `better` responses among `better|same|worse`; report `not_sure` separately.
- Tester-level guardrail: no tester should have a track acceptance rate below 20% across the prescribed sessions.
- Explanation metric: median explanation usefulness of at least 4/5 and no evidence card accuracy complaints left unresolved.
- Product metrics: selected-track rate, playlist export rate, return-session rate, source coverage, cache hit rate, and recommendation generation latency.
- Required protocol: each tester completes at least three sessions on separate prompts: comfort-zone discovery, a mood/activity request, and an adventurous request. Prompt order is rotated across testers.
- Before first use, collect a one-question baseline about satisfaction with current discovery. After every session, capture the comparison and explanation ratings before showing aggregate results.
- Do not use five users for significance testing or broad market claims. Report counts, medians, per-user ranges, and uncertainty descriptively.
- Freeze ranking and source-adapter versions during the first evaluation round. Any bug fix or behavior change starts a new version and is analyzed separately.
- Keep qualitative comments linked to the session and ranking version. Convert repeated issues into Beads work, not silent weight changes.
- Explainable recommendation research can guide presentation and evaluation, including [user-aware explanation evaluation](https://arxiv.org/abs/2412.14193) and [explanation goals in recommender systems](https://arxiv.org/abs/1804.11192), while the implementation remains auditable and product-specific.

## Implementation Tasks

1. [x] Establish the policy, product, and implementation baseline.
   - Files: `docs/spotify-policy-assessment.md`, `docs/product-beta-acceptance.md`, Beads implementation epic and child issues
   - Notes: Record allowed Spotify fields, storage, transformations, display attribution, AI boundary, retention, five-user quota, and a go/no-go owner. Capture the exact beta success metrics and privacy placeholders. Create a fresh implementation branch from updated `main`, claim the Beads epic, and run all existing quality gates before changes.
   - Completed: Accepted an explicit-input policy boundary, documented beta acceptance, created and linked seven Beads phases, branched from current `main`, and passed Ruff, mypy, and all 125 baseline tests.

2. [x] Add an architecture decision record for Vercel, AWS, and Supabase.
   - Files: `docs/decisions/0001-vercel-aws-supabase.md`, `docs/recommender-architecture.md`
   - Notes: Document why there is no CloudFront, why Supabase is database-only, why custom Spotify OAuth remains in AWS, trust boundaries, request/data flows, failure domains, and rollback to the current single-user stack.
   - Completed: Added ADR 0001 and rewrote the recommender architecture for Vercel, AWS, backend-only Supabase, automated MusicBrainz/ListenBrainz APIs, custom Spotify OAuth, no CloudFront, and no local/S3 product data.

3. [x] Scaffold and validate the Supabase schema locally.
   - Files: `supabase/config.toml`, `supabase/migrations/<timestamp>_beta_core.sql`, `tests/integration/test_supabase_schema.py`
   - Notes: Write schema assertions first. Add enums/checks, all proposed tables, foreign keys, indexes, RLS/grants, cleanup SQL, and transaction-safe OAuth-state consumption. Do not add fake tester seed rows or committed credentials.
   - Completed: Added database-only Supabase local configuration, a core migration, and 26 pgTAP assertions covering tables, RLS/grants, indexes, the five-user/seed caps, and one-time OAuth state. `supabase db reset`, `supabase test db`, and `supabase db lint --local` pass.

4. [x] Add typed database configuration and connection lifecycle.
   - Files: `src/music_recommender/config.py`, `src/music_recommender/storage/postgres.py`, `src/music_recommender/storage/__init__.py`, `infra/lambda/api-requirements.in`, `infra/lambda/discovery-worker-requirements.in`, `.env.example`, `tests/test_config.py`, `tests/test_postgres_storage.py`
   - Notes: Add `supabase` runtime mode, TLS pooler DSN, bounded pool settings, query timeout, and transaction helpers. Reuse connections across warm Lambda invocations but acquire/release per request. Redact DSNs from errors and health output. Confirm `psycopg` dependencies fit the Lambda unzipped-size limit.
   - Completed: Added redacted Supabase/Postgres settings, remote TLS validation, bounded lazy pooling, tenant/system transaction helpers, psycopg dependencies and Lambda pins, unit tests, and a passing real local Supabase connection test. Full Ruff, mypy, and Python tests pass (133 passed, one opt-in integration test skipped in the default run). SAM builds with no Parquet/CSV files, but the legacy API artifact is 244,796 KB; Beads `music-recommender-0zg.6.1` requires a thin product package before deployment.

5. [x] Introduce foundational account-scoped repository protocols and Postgres adapters.
   - Files: `src/music_recommender/storage/protocols.py`, `src/music_recommender/storage/postgres.py`, `src/music_recommender/api/services.py`, `tests/test_postgres_storage.py`, existing DynamoDB store tests
   - Notes: Define explicit repositories for users/tokens, sessions, OAuth state, user seeds, and external entities/cache/jobs. Every user-owned method requires `account_id`; ownership mismatches return no record. Add recommendation/item, feedback, export, and evaluation adapters with tasks 17-19 once their service contracts exist, avoiding speculative repository APIs. Keep existing DynamoDB adapters available only for legacy routes.
   - Completed: Added typed protocols and Postgres adapters for users/tokens, one-time OAuth state, active sessions, canonical music entities, explicit account seeds, normalized source cache, and idempotent discovery jobs. Local integration tests prove status preservation, one-time consumption, revocation, account isolation, cache expiry, and job replay.

6. [x] Add the KMS-backed Spotify token vault.
   - Files: `src/music_recommender/security/token_vault.py`, `src/music_recommender/security/__init__.py`, `tests/test_token_vault.py`, `src/music_recommender/config.py`, `tests/test_config.py`
   - Notes: Test encryption context, rotation replacement, access-denied handling, and redaction first. Implement the backend vault and key-ID configuration locally; add the customer-managed key/alias and least-privilege policies with task 27 before deployment. Never log token plaintext, ciphertext, authorization codes, or KMS responses.
   - Completed: Added a redacted KMS vault bound to `{purpose, account_id}`, key-ID configuration, input/payload validation, AWS failure handling, and transactional refresh-ciphertext replacement that preserves account approval state. Focused tests and local Postgres rotation integration pass; cloud key/IAM creation remains in task 27.

7. [x] Modernize and harden the Spotify client before OAuth integration.
   - Files: `src/music_recommender/sources/spotify_user.py`, `tests/test_spotify_user_client.py`
   - Notes: Add PKCE challenge/verifier support, use `POST /me/playlists` and `/playlists/{id}/items`, expose `account_id`, handle refresh-token rotation, classify `401/403/429/5xx`, honor `Retry-After`, and add bounded pagination. Keep access tokens in memory only.
   - Completed: Added RFC 7636 verifier/challenge support, explicit `account_id` identity, refresh-token rotation publication, redacted Spotify error classes, bounded retry coverage, and current-user playlist writes through `/me/playlists` and playlist `/items`. Removed caller-supplied Spotify user IDs from the playlist service contract; all focused client and legacy playlist tests pass.

8. [x] Implement OAuth state, application sessions, CSRF, and current-user dependencies.
   - Files: `src/music_recommender/auth/models.py`, `src/music_recommender/auth/oauth.py`, `src/music_recommender/auth/sessions.py`, `src/music_recommender/api/dependencies.py`, `tests/test_oauth_service.py`, `tests/test_session_auth.py`
   - Notes: Use cryptographically random values, one-time state consumption, PKCE, hashed opaque sessions, cookie helpers, idle/absolute expiry, session rotation after OAuth, Origin checks, and double-submit CSRF. Use injectable clocks/random sources for deterministic tests.
   - Completed: Added KMS-bound PKCE verifier storage, hashed one-time OAuth state, strict internal return paths, opaque hash-only sessions with 7-day idle/30-day absolute expiry, safe session rotation, secure `__Host-` cookie helpers, exact-Origin double-submit CSRF, sliding-session SQL that cannot revive expired sessions, and reusable FastAPI authentication/mutation dependencies. Focused unit tests and live Postgres integration pass.

9. [x] Add product authentication routes and compatibility-mode middleware.
   - Files: `src/music_recommender/api/app.py`, `src/music_recommender/api/routes/auth.py`, `src/music_recommender/api/models.py`, `src/music_recommender/api/errors.py`, `tests/test_auth_api.py`, `tests/test_api_health.py`
   - Notes: Test start/callback/pending/approved/revoked/logout/delete flows before implementation. Replace global API-key assumptions with route-aware `AUTH_MODE`, secure cookie responses, stable error codes, sanitized redirects, and a shallow `/health` plus dependency-aware `/ready` that reveals no secret/config inventory.
   - Completed: Added environment-validated `api_key|hybrid|spotify_session` runtime wiring, Spotify start/callback/me/logout routes, pending/revoked/onboarding redirects, approved and reconnect-aware dependencies, stable redacted auth errors, secure cookie clearing, a shallow health response, and a database-backed readiness probe. Legacy routes remain API-key protected in hybrid mode and fail closed in session-only mode. Account deletion remains intentionally deferred to task 20.

10. [x] Implement the deny-by-default five-user administration CLI.
   - Files: `src/music_recommender/beta_admin_cli.py`, `pyproject.toml`, `tests/test_beta_admin_cli.py`, `docs/operational-aws-runbook.md`
   - Notes: Add `pending`, `approve`, `revoke`, and `status` commands. Enforce the five-approved-user cap in one database transaction. Read credentials through existing settings/Secrets Manager patterns and print only necessary account/status information.
   - Completed: Added `outside-the-loop-beta-admin` with pending/approve/revoke/status commands, an advisory-lock-protected Postgres approval repository, the database trigger as a second cap, redacted account-only JSON output, and atomic revocation that removes refresh-token ciphertext and revokes active sessions. Runbook command examples remain part of task 32.

11. [x] Implement explicit seed search and account-scoped seed management.
    - Files: `src/music_recommender/sources/musicbrainz.py`, `src/music_recommender/api/routes/music.py`, `src/music_recommender/product/seed_service.py`, `src/music_recommender/api/models.py`, `tests/test_musicbrainz_client.py`, `tests/test_seed_api.py`
    - Notes: Search canonical MusicBrainz artists/recordings with bounded plain-text queries, require explicit confirmation, store one to five owned seeds, use a contactable User-Agent, and enforce a distributed one-request-per-second limit plus positive/negative Supabase caching. Do not accept Spotify profile data as a seed source.
   - Completed: Added normalized MusicBrainz artist/recording search, contact-email configuration, redacted upstream failures, seven-day positive and one-hour negative Supabase caches, a database-coordinated source rate limiter, canonical entity persistence, and approved-session `/music/search` plus `/me/seeds` routes. Seed writes derive the account from the session and accept only one to five fresh MBIDs confirmed through search. Product services live under `music_recommender/product/` because the existing `api/services.py` module prevents a same-name package without a legacy refactor.

12. [x] Implement automated ListenBrainz discovery jobs and normalized caches.
    - Files: `src/music_recommender/sources/listenbrainz_api.py`, `src/music_recommender/api/routes/discovery.py`, `src/music_recommender/product/discovery_service.py`, `src/music_recommender/product/discovery_queue.py`, `src/music_recommender/api/discovery_worker_handler.py`, `tests/test_listenbrainz_api.py`, `tests/test_discovery_service.py`, `tests/test_discovery_queue.py`, `tests/test_discovery_worker_handler.py`, `tests/test_discovery_data_policy.py`
    - Notes: Add Core API artist/tag LB Radio and recording metadata adapters, artist-credit fallback for recording seeds, FIFO SQS idempotency, source rate-limit handling, bounded normalized cache writes, and redacted job errors. Keep experimental Labs disabled until a separate coverage review. No product code may read local or S3 catalog files.
    - Completed: Added approved-account discovery enqueue/status routes, deterministic seed fingerprints, FIFO SQS publishing, partial-batch Lambda processing, three-attempt transient source retries, distributed ListenBrainz rate deferral, seven-day positive and one-hour negative Supabase caches, normalized titles/credits/ISRCs/releases/tags/candidate edges, and explicit no-local/S3/CSV/Parquet discovery policy tests. Live Core API verification returned candidates and recording metadata without a user token or file input.

13. [x] Implement post-ranking Spotify ID mapping and source coverage gates.
    - Files: `src/music_recommender/sources/spotify_user.py`, `src/music_recommender/product/spotify_mapping.py`, `src/music_recommender/product/source_audit.py`, `src/music_recommender/storage/protocols.py`, `src/music_recommender/storage/postgres_repositories.py`, `scripts/audit_beta_sources.py`, `tests/test_spotify_mapping.py`, `tests/test_source_audit.py`, `docs/data-extraction.md`
    - Notes: Map ranked MusicBrainz recordings to Spotify IDs only for display/export, never as a score input. Audit source provenance, duplicate filtering, cache freshness, mapping coverage, and evidence coverage without profile records. Require enough fresh candidates for a 10-track result and verifiable evidence for 90% of returned tracks; otherwise return an honest degraded/insufficient state.
    - Completed: Added bounded Spotify track search, exact-ISRC then exact-title/artist matching, 24-hour Postgres mapping persistence, order-preserving post-ranking mapping, duplicate filtering, ten-track and 90% evidence gates, and an aggregate Supabase source audit that writes no file. A regression test proves a zero-popularity exact ISRC beats a high-popularity wrong ISRC, and product extraction documentation now makes the API-to-Supabase path authoritative over the isolated legacy medallion pipeline.

14. [x] Replace the production intent/orchestration path with a policy-safe parser.
    - Files: `src/music_recommender/agents/intent.py`, `src/music_recommender/api/models.py`, `tests/test_product_intent.py`, existing legacy agent tests
    - Notes: Remove `use_openai_agent` from product requests and prevent catalog/profile/external-source tools from running in production. Default to deterministic parsing; if an LLM is configured, send only user-authored prompt text and validate a strict intent schema. Add a regression test that fails if Spotify, account, seed history, or candidate fields enter the LLM request.
    - Completed: Added a deterministic prompt-to-tag product parser with explicit adventure/explicit controls and versioning. Its optional model boundary accepts one normalized prompt string and rejects any output beyond a strict label/tags schema. The extra-forbid product request contract rejects agent switches, playlist side effects, caller user IDs, profile fields, and catalog run IDs. Legacy agent orchestration remains isolated behind the legacy API-key service and is not imported by the product service contract.

15. [x] Implement and version the discovery-first ranker.
    - Files: `src/music_recommender/recommender/scoring.py`, `src/music_recommender/recommender/models.py`, `tests/test_discovery_ranking.py`, existing legacy ranking tests
    - Notes: Write failing tests for exact filtering, component weights, adventure adjustments, evidence-quality fallback, deterministic tie-breaking, feedback preferences, and artist diversity. Remove Spotify popularity from scoring and stop presenting total decimal scores as confidence.
    - Completed: Added the frozen `explicit-discovery-v1` ranker over MusicBrainz entities and ListenBrainz edges. It scores prompt/tag fit, seed bridge, discovery value, and evidence quality; familiar/adventurous controls shift ten points only between bridge and discovery weights. It filters selected, blocked, and source-established explicit recordings, merges duplicate edges, applies first-party recording/artist blocks, enforces one result per primary artist, and resolves ties by MBID. Product score types contain no Spotify ID or popularity field and remain internal.

16. [x] Implement structured evidence generation and provenance validation.
    - Files: `src/music_recommender/recommender/evidence.py`, `src/music_recommender/recommender/models.py`, `src/music_recommender/api/models.py`, `tests/test_recommendation_evidence.py`
    - Notes: Generate only from auditable score components/source metadata, enforce allowed reason kinds/sources, include coverage limitations, and reject unsupported explanation claims. Snapshot evidence with the recommendation session for reproducibility.
    - Completed: Added `evidence-v1` structured cards for selected seed, source edge, direct tag match, listener support, and multi-adapter discovery. Every reason has a fixed source and exact detail schema that is revalidated against the ranked candidate before persistence. Sparse records disclose missing tag, listener, artist, title, and explicit-status coverage instead of inventing prose; evidence exposes neither internal decimal scores nor Spotify-based recommendation claims.

17. [x] Build account-scoped recommendation, selection, and history services.
    - Files: `src/music_recommender/product/recommendation_service.py`, `src/music_recommender/product/spotify_account.py`, `src/music_recommender/api/routes/recommendations.py`, `src/music_recommender/api/models.py`, `src/music_recommender/storage/protocols.py`, `src/music_recommender/storage/postgres_repositories.py`, `supabase/migrations/20260710170000_recommendation_coverage_statuses.sql`, `tests/test_recommendation_service.py`, `tests/test_product_recommendations_api.py`, `tests/test_spotify_account.py`, Postgres integration tests
    - Notes: Remove caller-selected users/runs/profile signals from the public contract, validate owned seed IDs, persist session/items transactionally, implement cursor pagination and selection ordering, and return `404` for cross-tenant IDs. Add ranking/source adapter/fetch versions to every response.
    - Completed: Added approved-session `/me/recommendations` create/get/history/review routes, owned active-seed validation, fresh Supabase candidate loading, deterministic ranking/evidence, post-ranking current-account Spotify mapping and explicit filtering, duplicate Spotify ID removal, atomic session/item snapshots, opaque cursor history, and review ordering with explicit playlist name/visibility. KMS-decrypted refresh tokens exist only in the backend client and rotations are re-encrypted transactionally. Cross-account sessions return `404`; product responses omit account IDs and internal scores while retaining ranking, source adapter, algorithm, fetch, evidence, and coverage versions.

18. [x] Make playlist export an explicit, current-user, idempotent action.
    - Files: `src/music_recommender/product/playlist_export_service.py`, `src/music_recommender/api/routes/playlists.py`, `src/music_recommender/api/models.py`, `src/music_recommender/sources/http.py`, `src/music_recommender/sources/spotify_user.py`, `src/music_recommender/storage/protocols.py`, `src/music_recommender/storage/postgres_repositories.py`, `tests/test_playlist_export_service.py`, `tests/test_product_playlist_export_api.py`, `tests/test_spotify_user_client.py`, Postgres integration tests
    - Notes: Require review, explicit name, visibility, ordered owned track IDs, and `Idempotency-Key`. Use `/me/playlists` and `/items`; persist the playlist ID before adding tracks so retries resume safely. Verify same-payload replay and different-payload conflict behavior.
    - Completed: Added current-account `/me/recommendations/{session_id}/playlist` export with an extra-forbid payload, mandatory idempotency header, exact reviewed order/name/visibility validation, canonical request fingerprint, advisory-lock Postgres reservation, and same-payload replay/different-payload conflict handling. The backend creates through `/me/playlists`, persists the playlist ID, then uses idempotent `PUT /playlists/{id}/items` replacement so transient retries cannot duplicate tracks. Automatic POST retries are disabled; an uncertain creation outcome is frozen for manual reconciliation instead of risking a duplicate playlist. Recommendation generation itself remains read-only.

19. [x] Add account-scoped feedback, preferences, and beta evaluations.
    - Files: `src/music_recommender/product/feedback_service.py`, `src/music_recommender/api/routes/feedback.py`, `src/music_recommender/api/routes/evaluations.py`, `src/music_recommender/api/models.py`, `src/music_recommender/storage/protocols.py`, `src/music_recommender/storage/postgres_repositories.py`, `src/music_recommender/beta_admin_cli.py`, `tests/test_feedback_evaluation_service.py`, `tests/test_product_feedback_api.py`, `tests/test_beta_admin_cli.py`, Postgres integration tests
    - Notes: Validate event ownership/idempotency, translate hide/dislike into explicit account preferences, cap metadata/comment size, and never aggregate five-user feedback into a global ranker. Add evaluation completeness reporting for beta operations.
    - Completed: Added item-owned idempotent feedback and account-owned evaluation APIs. The product accepts only a bounded optional reason, not arbitrary metadata; `dislike` blocks that recording and `hide_artist` blocks MusicBrainz artist MBIDs for the initiating account only. Evaluation comparison, usefulness, novelty, and comments are bounded and updatable per owned session. Postgres foreign keys and service checks prevent cross-account writes, while `beta-admin evaluations` emits only aggregate approved/session/evaluation counts. No feedback aggregation enters ranker weights.

20. [x] Add privacy, deletion, retention, and cleanup behavior.
    - Files: `src/music_recommender/product/account_service.py`, `src/music_recommender/api/routes/auth.py`, `src/music_recommender/api/cleanup_handler.py`, `src/music_recommender/storage/protocols.py`, `src/music_recommender/storage/postgres_repositories.py`, `tests/test_account_deletion.py`, `tests/test_account_deletion_api.py`, `tests/test_cleanup_handler.py`, Postgres integration tests, `docs/privacy-notice.md`
    - Notes: Test cascade deletion, session/token invalidation, expired OAuth/session/cache cleanup, source TTL retention, and failure retries. Add a daily cleanup schedule and a beta privacy notice with explicit seeds, external APIs, data categories, purpose, retention, Spotify attribution, deletion method, and contact placeholder gate.
    - Completed: Added CSRF-protected `DELETE /auth/me` with exact confirmation, hard account deletion, cascade tests covering token/session/seed/recommendation/feedback/evaluation records, cookie clearing, bounded retention SQL for OAuth state, sessions, caches, edges, mappings, jobs, removed seeds, old recommendations, and unreferenced entities, plus an EventBridge handler that raises for retry on failure. The beta privacy notice documents data, purposes, providers, retention, security, Spotify boundaries, and deletion with an explicit contact placeholder gate. The daily AWS schedule is intentionally wired with task 27.

21. [x] Scaffold the Vercel frontend and shared API client.
    - Files: `web/package.json`, `web/package-lock.json`, `web/tsconfig.json`, `web/vite.config.ts`, `web/vercel.json`, `web/index.html`, `web/src/main.tsx`, `web/src/app/App.tsx`, `web/src/api/client.ts`, `web/src/styles/*`
    - Notes: Use React, TypeScript, Vite, React Router, TanStack Query, Zod, Lucide icons, Vitest/Testing Library/MSW, and Playwright. Calls use relative `/api`; local Vite proxies to a configurable local API. Put the external API Gateway rewrite before the SPA fallback. Do not add CloudFront or privileged `VITE_*` secrets.
    - Completed: Added the React 19/TypeScript 6/Vite application, router, TanStack Query auth bootstrap, strict Zod response validation with sanitized failures, relative same-origin API client, local proxy, Lucide controls, responsive visual system, ESLint, Vitest, and Playwright. The concrete Vercel external rewrite is intentionally completed with task 29 after the real API Gateway origin exists; no placeholder origin or browser secret was added.

22. [x] Implement sign-in, pending access, onboarding, and auth recovery UI.
    - Files: `web/src/routes/LoginPage.tsx`, `web/src/routes/AccessPendingPage.tsx`, `web/src/routes/OnboardingPage.tsx`, `web/src/auth/AuthProvider.tsx`, `web/src/components/AppShell.tsx`, corresponding tests
    - Notes: The first screen is focused Spotify sign-in. Handle denied OAuth, expired state, pending/revoked access, seed onboarding, discovery queued/degraded/failed, reconnect states, logout, and keyboard/screen-reader behavior. Do not expose provider tokens or raw account IDs.
    - Completed: Added focused Spotify sign-in, public privacy access, pending/revoked gates, reconnect and auth-outage states, explicit MusicBrainz seed onboarding, logout, and accessible controls. Backend callback recovery now consumes denied/expired OAuth state and redirects to stable frontend error codes without creating a Spotify session or exposing callback values.

23. [x] Implement the discovery composer and evidence-card results.
    - Files: `web/src/routes/DiscoverPage.tsx`, `web/src/routes/SessionPage.tsx`, `web/src/components/DiscoveryForm.tsx`, `web/src/components/RecommendationList.tsx`, `web/src/components/EvidenceCard.tsx`, corresponding tests
    - Notes: Provide MusicBrainz-backed artist/recording seed search and confirmation, prompt, segmented adventure control, explicit toggle, and blocked-artist management. Render loading, discovery queued, sparse-evidence, empty, source-rate-limited, degraded, and error states without layout shifts. Evidence is visible by default, concise, and expandable for provenance.
    - Completed: Added explicit seed editing, prompt/adventure/explicit controls, queued source polling, degraded/error/empty states, result rows, visible evidence and expandable provenance. Added account-scoped preference listing and idempotent artist unblocking backed only by Supabase product records.

24. [x] Integrate Spotify preview/link behavior with correct attribution.
    - Files: `web/src/components/SpotifyEmbed.tsx`, `web/src/components/TrackActions.tsx`, `web/src/lib/spotifyEmbed.ts`, corresponding tests
    - Notes: Load the Spotify iFrame API once, render only one active embed at a time, provide Open Spotify links, retain Spotify artwork aspect ratios/attribution, and provide a non-playing fallback. Verify no artwork is proxied or persisted by the app.
    - Completed: Added the current official Spotify iFrame API singleton, one-active-embed interaction, non-playing fallback, and attributed Open Spotify links. The app neither fetches nor stores artwork itself, and a regression test proves only one embed remains mounted.

25. [x] Implement review-first playlist export UI.
    - Files: `web/src/routes/ReviewPage.tsx`, `web/src/components/TrackReviewList.tsx`, `web/src/components/PlaylistExportForm.tsx`, corresponding tests
    - Notes: Support remove, accessible reorder, editable generated name, description, explicit public/private toggle, confirmation, in-flight lock, idempotent retry, partial-failure recovery, and Open Spotify success action. The frontend must never call recommendation generation with `create_playlist=true`.
    - Completed: Added accessible reorder/remove review, editable name/description/visibility, explicit create action, in-flight lock, payload-versioned session idempotency keys, safe retries, error recovery, and Spotify success link. Component and E2E assertions prove review precedes export and generation contains no playlist side effect field.

26. [x] Implement history, evaluation, settings, privacy, and deletion UI.
    - Files: `web/src/routes/HistoryPage.tsx`, `web/src/routes/SettingsPage.tsx`, `web/src/routes/PrivacyPage.tsx`, `web/src/components/SessionEvaluation.tsx`, corresponding tests
    - Notes: Add paginated session history, post-session comparison/usefulness prompts, reconnect, blocked artists, logout, and destructive account deletion confirmation. Keep operational instructions out of visible product UI.
    - Completed: Added cursor history, frozen beta comparison/usefulness/novelty evaluation, reconnect/logout, seed and blocked-artist management, public/account privacy notice, and exact `DELETE` account confirmation. Frontend quality gates pass with 13 component tests, 3 Playwright flows at 1440x900 and 375x812, lint, typecheck, and production build.

27. [x] Extend AWS SAM for the multi-user runtime.
    - Files: `infra/template.yaml`, `infra/README.md`, `tests/test_infra_template.py`, `infra/lambda/*.in`, generated requirements lock files
   - Notes: Add Supabase secret references, app/session settings, KMS, discovery SQS/DLQ, external-source worker, cache cleanup schedule, scoped IAM, reserved concurrency, API/source throttling, logs, alarms, and outputs. Product functions receive no S3 data configuration or permissions. Preserve existing DynamoDB/S3 resources only for the separate legacy function during `hybrid` rollout.
   - Completed: Added the product HTTP API, rotating retained KMS key, FIFO discovery queue/DLQ, thin API/worker/cleanup Lambdas, daily cleanup, bounded concurrency/throttling, redacted logs, EMF metrics, CloudWatch alarms, encrypted SNS notification, and product outputs. Every product function is free of S3 configuration/IAM; all legacy resources default off behind `DeployLegacyDemo=false`.

28. [x] Harden packaging and deployment scripts.
    - Files: `scripts/prepare_lambda_build.sh`, `scripts/prune_lambda_artifacts.sh`, `scripts/sync_runtime_secret.sh`, `scripts/deploy_api_sam.sh`, `scripts/smoke_test_deployed_api.sh`, `tests/test_deployment_scripts.py`
   - Notes: Add required-value validation for database/session/app URL/source settings without printing values, migration preflight, Supabase connectivity readiness, and new auth/seed/discovery/recommendation/export smoke phases. Fail packaging if any local catalog, Parquet, or CSV file exists in product Lambda artifacts; report only artifact sizes and safe identifiers.
   - Completed: Added isolated product build locks/contexts, migration and secret-shape preflight, redacted secret sync, product-only deploy/smoke wrappers, package headroom limits, and explicit `.env`/Parquet/CSV rejection. The deployment script reaches no S3 path unless the separately gated legacy condition is explicitly enabled.

29. [x] Add Vercel deployment configuration and environment validation.
    - Files: `web/vercel.mjs`, `scripts/verify_vercel_deployment.sh`, `docs/vercel-deployment-runbook.md`, frontend tests
   - Notes: Create the Vercel project first to obtain its stable production domain, then configure the exact Spotify callback and AWS `APP_BASE_URL`. Rewrite `/api/:path*` to the current API Gateway origin and all other routes to `index.html`. Validate cookies survive the rewrite, APIs are not cached, preview OAuth is disabled, and no secret is present in the build output.
   - Completed: Added validated programmatic Vercel configuration, API-first rewrite ordering, SPA fallback, no-store API responses, CSP/security headers, production/preview OAuth policy, secret-marker checks, and a deployment verifier covering deep links, OAuth redirects, and the API facade.

30. [x] Add CI and credential-safe deployment automation.
    - Files: `.github/workflows/ci.yml`, `.github/workflows/deploy-aws.yml`, repository/Vercel settings documentation
   - Notes: Run Python, SQL migration, frontend, Playwright mocked-E2E, SAM, package-content, and secret-scan gates. Use GitHub OIDC to assume a scoped AWS deployment role; stop deploying with root AWS credentials. Let Vercel Git integration deploy `web/` after CI. Require manual approval for production DB migrations and AWS deployment.
   - Completed: Added CI jobs for Python, local Supabase/pgTAP/integration, frontend, Playwright, SAM/package policy, and Gitleaks. Added a manually approved AWS production workflow using GitHub OIDC and product-only deployment with no static AWS key fields.

31. [x] Add product observability, audit-safe metrics, and alerting.
    - Files: `src/music_recommender/observability.py`, `infra/template.yaml`, tests, `docs/operational-aws-runbook.md`
   - Notes: Emit structured request IDs, hashed internal user correlation, route latency, source/cache coverage, source status class, Spotify export status, playlist outcome, queue age, and DLQ depth. Never log prompts with account identity, cookies, auth headers, tokens, raw external payloads, or comments. Alarm on API/worker errors, latency, database/source failures, reconnect spikes, and DLQ messages.
   - Completed: Added dependency-free CloudWatch EMF observation for API latency/status, HMAC user correlation, recommendation coverage, source/cache behavior, playlist outcomes, reconnects, queue age, worker status, and cleanup. Added fail-open logging behavior, sensitive-field regression tests, Lambda/SQS/custom alarms, and SNS operator notification.

32. [x] Update API, deployment, architecture, privacy, and methodology runbooks.
    - Files: `README.md`, `docs/api-usage-runbook.md`, `docs/aws-deployment-architecture-runbook.md`, `docs/operational-aws-runbook.md`, `docs/recommender-methodology-runbook.md`, `docs/vercel-deployment-runbook.md`
   - Notes: Include exact curl/Postman examples using browser sessions where practical, OAuth flow, explicit playlist name/public payload, user ownership guarantees, Supabase migration/recovery, Vercel rewrite, no-CloudFront rationale, five-user approval, token reconnect, data deletion, scientific protocol, rollback, and secret-redaction rules.
   - Completed: Replaced the stale single-user/API-key/S3 guidance with product-first API, AWS architecture/operations, Vercel, infrastructure, privacy-linked, and scientific runbooks. Added executable request examples, five-user administration, deployment/recovery, no-file boundaries, review-first export, evidence/ranking methodology, and documentation drift tests.

33. [x] Validate locally with unit, integration, contract, UI, security, and package tests.
    - Files: all changed code/tests and generated build artifacts outside git
   - Notes: Start local Supabase, reset migrations, run the complete Python and frontend suites, mock Spotify failure/retry paths, run cross-tenant/security tests, build SAM and Vercel artifacts, and prove no credentials, Parquet, or CSV files are included. Resolve every failure before deployment.
   - Completed: Reset local Supabase, passed 32 pgTAP assertions and seven live Postgres integrations, 298 Python tests, Ruff/mypy, 13 frontend component tests, three desktop/mobile Playwright flows, npm audit/lint/typecheck/build, Vercel secret scanning, SAM lint/build/prune, migration preflight, and package policy/import checks. Product artifacts are 31,584 KB (API), 22,960 KB (worker), and 20,868 KB (cleanup), with no `.env`, Parquet, CSV, web framework dependency in worker/cleanup, or privileged frontend marker.

34. [x] Provision Supabase and deploy AWS in compatibility mode.
    - Files: production Supabase project, AWS Secrets Manager/KMS/SQS/Lambda/API Gateway/CloudWatch resources
    - Notes: Create the project in the selected region, enable backups, apply migrations, create least-privilege pooler credentials, update Secrets Manager, deploy `AUTH_MODE=hybrid`, verify stack outputs/alarms/DLQ, and run database/API readiness without printing credentials. Keep legacy API-key smoke behavior available during rollback window.
    - Completed: Provisioned the healthy `us-east-1` Supabase project with WAL-G backup enabled, applied four migrations, rotated Lambda to the restricted `outside_loop_runtime` role through Supavisor transaction mode, and deployed the product-only AWS stack in `hybrid` mode. Scoped OIDC/deployment and CloudFormation roles, Secrets Manager, KMS, FIFO queue/DLQ, workers, cleanup, logs, alarms, and SNS are live; readiness/OAuth-start smoke passes and the DLQ is empty. The new empty database has not yet produced its first scheduled physical backup.

35. [ ] Deploy the Vercel production frontend and complete Spotify configuration.
    - Files: Vercel project/settings and Spotify developer dashboard configuration
    - Notes: Deploy once for the stable URL, register its exact `/api/auth/spotify/callback`, configure the AWS app URL, deploy the final rewrite-enabled frontend, and add the five testers to Spotify's dashboard when identities are supplied. Verify CSP, cookies, deep links, attribution, and mobile/desktop layout against production.
   - Current: `https://outside-the-loop.vercel.app` is deployed and verified on desktop/mobile, AWS uses the stable origin, and the live OAuth redirect requests exactly `user-read-private`, `playlist-modify-private`, and `playlist-modify-public`. Saving the callback and tester identities in the Spotify dashboard still requires the product owner.

36. [ ] Run live multi-user end-to-end acceptance and switch auth mode.
    - Files: deployed Vercel/AWS/Supabase/Spotify resources and redacted smoke evidence
    - Notes: Test the owner first, then at least one second allowlisted account when available: pending login, approval, explicit seed search/selection, automated discovery, account-isolated recommendation, evidence, review/reorder, custom public and private playlist names, Spotify visibility in the correct accounts, feedback, evaluation, history, logout, reconnect simulation, and deletion. Prove cross-account seed/session IDs cannot be read or exported. Switch to `AUTH_MODE=spotify_session` only after these pass.

37. [ ] Execute the frozen five-tester beta and produce the decision report.
    - Files: `docs/beta-results/<date>-explicit-discovery-v1.md`, Beads findings/issues
    - Notes: Run the prescribed three-session protocol, export aggregate/non-identifying metrics, summarize per-user ranges and comments, compare against success thresholds, and create Beads issues for evidence errors or quality gaps. Do not change ranking weights during the frozen round.

38. [ ] Complete release review, rollback rehearsal, documentation, and push.
    - Files: plan completion evidence, runbooks, Beads issue state, git history
    - Notes: Perform security/policy/accessibility review, restore the previous API configuration in a non-production rehearsal, verify database backup recovery steps, close completed Beads issues, file unresolved follow-ups, commit cohesive changes, pull/rebase, push, and verify the branch is up to date with origin.

## Tests And Scenarios

- Unit tests: PKCE/state construction; one-time state consumption; cookie/session expiry; CSRF/Origin checks; KMS context and redaction; Spotify token rotation and 2026 write endpoints; MusicBrainz normalization/throttling; ListenBrainz rate handling; deterministic ranking components; evidence provenance; idempotency fingerprints; access-status transitions; account deletion.
- Database integration tests: migrations from empty database; constraints; at-most-five approval transaction; OAuth replay race; one equivalent discovery job; one-to-five active seeds; cache uniqueness/expiry; session hash lookup; recommendation/item transaction rollback; cross-account ownership; feedback/export idempotency; cascade deletion; connection recovery.
- API contract tests: all auth/music-search/seeds/discovery/recommendation/selection/playlist/feedback/evaluation/history endpoints; stable status/error codes; no user ID or Spotify profile override; no token/config leakage; cursor validation; body size limits; `404` for foreign resources; legacy compatibility only under `api_key|hybrid`.
- Spotify integration tests with fakes: consent denied, callback mismatch, missing scope, missing `account_id`, refresh rotation, six-month reconnect, `401`, `403`, `429 Retry-After`, transient `5xx`, public/private create via `/me/playlists`, `/items` chunking, partial add recovery, and idempotent replay. Product tests assert no top/library/recent/playlist-read call occurs.
- Recommender/source tests: explicit seed validation, MusicBrainz one-request-per-second coordination, ListenBrainz rate headers, expired/negative cache behavior, blocked/explicit filtering, no Spotify ranking fields, post-ranking ID mapping, minimum evidence, adventure weight shift, deterministic ties, one artist cap, sparse-source degraded state, first-party feedback boundaries, ranking/source version capture, and no LLM exposure of music/account data.
- Frontend component tests: auth bootstrap, pending/reconnect states, discovery control validation, loading/empty/errors, evidence expansion, one active embed, accessible reordering, playlist name override, visibility toggle, idempotent retry, history, survey, privacy, and deletion confirmation.
- Playwright mocked E2E: login callback simulation; pending approval; MusicBrainz seed search/confirmation; discovery queued to ready; recommendation to evidence to review to named playlist; partial export retry; second-user isolation; expired session; mobile navigation at 375x812; tablet and 1440px desktop; keyboard-only and screen-reader labels.
- Live E2E: exact Vercel callback; same-origin API rewrite; secure cookies; pending then approval; explicit seed selection; automated source discovery; playlist appears only in the initiating account; custom name and public/private state match; Spotify links/attribution work; no browser request reaches Supabase directly and no product request reads S3.
- Security tests: OAuth state replay, open redirect, session fixation, CSRF, forged Origin, cookie theft replay after logout, SQL injection, horizontal access attempts, idempotency-key collision, log capture scan, secrets/build scan, dependency audit, API throttling.
- Operational tests: discovery SQS retries and DLQ alarm; MusicBrainz global throttle; ListenBrainz backoff; one source/user failure does not block others; database outage returns safe errors; KMS denial fails closed; Supabase backup exists; API/worker alarms transition under controlled failure; rollback restores the legacy path.
- Packaging tests: product Lambda/Vercel artifacts stay within limits and contain no local catalog, `.parquet`, `.csv`, `.env`, token fixture, frontend source map with secrets, test cache, or local Supabase state.
- Beta methodology tests: every completed session records ranking/source/algorithm/fetch versions; each tester completes three prompt categories; evaluation cannot reference another user's session; aggregate reports suppress direct account identifiers; ranking stays frozen during round one.
- Regression scenarios: local CLI and legacy pipeline tests continue passing; legacy S3/DynamoDB behavior remains isolated in compatibility mode; product routes work with S3 variables absent; no live playlist is created during recommendation generation alone.

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
aws sqs get-queue-attributes --queue-url <discovery-dlq-url> --attribute-names ApproximateNumberOfMessages
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
9. Owner-first gate: the owner passes explicit seed, automated discovery, recommendation, evidence, named public/private playlist, feedback, history, and deletion tests; four approvals remain pending.
10. Two-user gate: once a second tester is available, prove identity, seed, session, and playlist isolation before enabling all five.
11. Five-user gate: add/approve only the final five accounts, verify source/cache/evidence coverage, then switch to `AUTH_MODE=spotify_session`.
12. Beta gate: freeze `explicit-discovery-v1`, run the three-session protocol, produce the report, and decide whether quality merits another iteration.

## Risks And Rollback

- Risk: A future change accidentally reintroduces Spotify profile/content analysis.
  Mitigation: Enforce `docs/spotify-policy-assessment.md`, omit profile-read scopes, separate legacy routes, test that product ranking inputs contain no Spotify-derived fields, and never train AI on music/account data.
  Rollback: Disable product invitations/routes, remove the disallowed path in a forward migration, and operate only the explicit-input subset.
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
- Risk: Automated MusicBrainz/ListenBrainz sources have insufficient coverage, rate limits, or downtime.
  Mitigation: Cache normalized results in Supabase, obey MusicBrainz's one-request-per-second rule, honor ListenBrainz rate headers, use core artist/tag radio before Labs endpoints, and gate on candidate/evidence coverage.
  Rollback: Show queued/degraded/insufficient-source states and collect different explicit seeds; do not fall back to Spotify analysis, ReccoBeats, local files, S3, or unsupported evidence.
- Risk: Five-user feedback is noisy and easy to overfit.
  Mitigation: Freeze one ranking version, prescribe prompt categories, report per-user outcomes, and treat results as directional.
  Rollback: Do not claim superiority; use findings only to choose the next hypothesis and beta iteration.
- Risk: Playlist export creates visible side effects or duplicates.
  Mitigation: Require review/confirmation, explicit account/name/visibility display, idempotency keys, persisted playlist IDs, and partial-add recovery.
  Rollback: Link the created playlist for user deletion, stop retrying completed creation, and remove the export record only after an operator confirms state.
- Risk: Added Postgres/KMS dependencies push Lambda past package limits.
  Mitigation: Measure every build, prune tests/caches/data, package no local catalog/Parquet/CSV, and consider a Lambda layer or separate thin API package if headroom drops below 10%.
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
- The architecture decision is explicit: Vercel frontend; AWS API/workers/KMS/Secrets/observability; Supabase Postgres; automated MusicBrainz/ListenBrainz APIs; custom AWS Spotify OAuth; no CloudFront; and no local/S3 product data path.
- Supabase Auth is deliberately excluded because Spotify provider refresh-token lifecycle still requires application handling. Revisit only if an SSR callback design can prove equivalent token custody with less complexity.
- Do not expose or print the existing API key, Spotify client secret, refresh tokens, session cookies, Supabase DSN, KMS plaintext, or OAuth codes. Test fixtures must use obvious fake values.
- Never accept user/account identity from a recommendation or playlist request. The authenticated session is the only ownership source.
- Playlist creation is review-first. Recommendation generation must have no Spotify write side effect in the final product mode.
- The playlist name in the export request overrides the generated suggestion, and the exported playlist must appear in the Spotify account that completed OAuth for that session.
- Keep Vercel preview deployments useful with mocked/local APIs, but only the stable production domain participates in live Spotify OAuth.
- Do not package or query local catalog, Parquet, CSV, or S3 product data. Existing S3 objects remain legacy-only and must not be copied into product build directories.
- Do not delete retained DynamoDB tables, remove legacy runbooks, or disable the live API until the two-user production gate and rollback rehearsal pass.
- Complete the five-user identity list, privacy contact, Supabase project, and Spotify policy signoff before sending tester invitations; none is a reason to weaken the deny-by-default code path.
