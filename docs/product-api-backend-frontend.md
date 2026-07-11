# Product API, Backend, And Frontend Technical Reference

This document describes the implemented Outside the Loop product application. It covers the
browser-facing API, backend service boundaries, frontend architecture, persistence, security, and
deployment contract. It applies when `DeployLegacyDemo=false`, which is the production setting.

Procedural curl and Postman examples remain in
[`api-usage-runbook.md`](api-usage-runbook.md). Deployment and incident procedures remain in the
AWS and Vercel runbooks. This reference explains how the pieces fit together and which code owns
each contract.

## Deployed Product Boundary

| Surface | Current value |
| --- | --- |
| Web application | `https://outside-the-loop.vercel.app` |
| Browser API base | `https://outside-the-loop.vercel.app/api` |
| AWS API origin | `https://gujy6gs0w3.execute-api.us-east-1.amazonaws.com` |
| Database | Supabase Postgres project `outside-the-loop-beta`, `us-east-1` |
| Authentication | Spotify OAuth plus opaque application session |
| Product capacity | Five approved Spotify Development Mode accounts |

Normal clients use the Vercel `/api` base. Vercel removes `/api` when forwarding to API Gateway,
so backend route definitions do not contain that prefix. Calling API Gateway directly is useful for
operator health checks, but it is not the supported browser authentication path because the secure
cookies belong to the Vercel host.

There is no product API key. `RECOMMENDER_API_KEY`, `X-API-Key`, profile-sync routes, S3 catalogs,
and DynamoDB repositories belong to the disabled legacy demo.

## Runtime Topology

```text
Browser
  -> Vercel React/Vite application
       -> same-origin /api rewrite
            -> API Gateway HTTP API
                 -> product FastAPI Lambda
                      -> Supabase Postgres
                      -> MusicBrainz seed search
                      -> Spotify OAuth, mapping, and playlist APIs
                      -> KMS token encryption
                      -> SQS FIFO discovery queue
                           -> discovery worker Lambda
                                -> ListenBrainz Core API
                                -> Supabase Postgres

EventBridge daily rule
  -> cleanup Lambda
       -> Supabase Postgres

API Gateway and Lambdas
  -> CloudWatch Logs, embedded metrics, X-Ray, alarms, and SNS email
```

Vercel serves static assets and the single-page application. AWS owns trusted application logic,
OAuth completion, user authorization, queueing, external writes, and observability. Supabase is a
managed external PostgreSQL service; the browser never connects to it directly.

There is no CloudFront distribution, VPC, NAT gateway, EC2 service, container service, AWS-hosted
relational database, or product data bucket. Lambda packages contain code and dependencies only;
CSV and Parquet files are rejected by packaging checks.

## Authentication And Authorization

### Spotify OAuth

The browser starts authentication at:

```text
GET /api/auth/spotify/start?return_to=/discover
```

The backend creates one-time state and a PKCE verifier, encrypts the verifier with KMS, and redirects
to Spotify. The product asks for exactly:

- `user-read-private` for the stable current-account identity.
- `playlist-modify-private` for private exports.
- `playlist-modify-public` for public exports.

The callback exchanges the authorization code server-side, fetches the current Spotify profile,
encrypts the refresh token, and creates or updates a pending application account. New users remain
blocked until an operator approves them. The database enforces a maximum of five approved,
non-deleted accounts.

### Application Session

Successful OAuth sets two secure cookies:

| Cookie | JavaScript access | Purpose |
| --- | --- | --- |
| `__Host-mr_session` | No, HTTP-only | Opaque application session token |
| `__Host-mr_csrf` | Yes | Double-submit CSRF token |

Only SHA-256 hashes are persisted. Sessions have a seven-day sliding idle lifetime and a 30-day
absolute lifetime. A new login revokes the previous active session represented by the incoming
cookie. Logout, account revocation, and account deletion revoke sessions.

Every mutating request must include:

```text
Cookie: __Host-mr_session=...; __Host-mr_csrf=...
Origin: https://outside-the-loop.vercel.app
X-CSRF-Token: <decoded __Host-mr_csrf value>
```

The backend compares the exact HTTPS origin, cookie token, header token, and stored CSRF hash.
Browser JavaScript cannot set `Origin`; the browser supplies it for same-origin mutations.

### Ownership Rules

The account ID always comes from the authenticated session. Product request bodies never accept an
account ID or Spotify user ID. Repositories scope all user-owned seeds, discovery jobs,
recommendation sessions, feedback, evaluations, and exports to that account. Cross-account UUIDs
return `404` instead of revealing that another user's record exists.

Pending or revoked users receive `403`. A user whose Spotify refresh token can no longer satisfy the
required scopes receives `409 spotify_reconnect_required` and must complete OAuth again.

## HTTP API Contract

The table lists backend paths. Browser clients prepend `/api`.

| Method and path | Access | Contract and side effect |
| --- | --- | --- |
| `GET /health` | Public | Shallow process/version check. |
| `GET /ready` | Public | Database readiness check; returns `503` when unavailable. |
| `GET /auth/spotify/start` | Public | Creates OAuth state and redirects to Spotify. |
| `GET /auth/spotify/callback` | Spotify redirect | Consumes state, stores encrypted credentials, and issues cookies. |
| `GET /auth/me` | Session | Returns safe user status; never returns an account ID or token. |
| `POST /auth/logout` | Session plus CSRF | Revokes the session and clears cookies. |
| `DELETE /auth/me` | Session plus CSRF | Requires `{"confirmation":"DELETE"}` and hard-deletes owned product data. |
| `GET /music/search` | Approved session | Searches MusicBrainz with `q` and `type=artist|recording`. |
| `GET /me/seeds` | Approved session | Lists one to five active account-owned seeds. |
| `PUT /me/seeds` | Approved plus CSRF | Atomically replaces active seeds with confirmed MusicBrainz MBIDs. |
| `POST /discovery/jobs` | Approved plus CSRF | Creates or reuses a seed-fingerprinted job and enqueues SQS work; returns `202`. |
| `GET /discovery/jobs/{job_id}` | Approved session | Reads an owned job and its bounded status/error code. |
| `POST /me/recommendations` | Approved plus CSRF | Generates and snapshots a recommendation session; returns `201`. |
| `GET /me/recommendations` | Approved session | Cursor-paginated history, `limit` 1-50. |
| `GET /me/recommendations/{session_id}` | Approved session | Returns one owned session, items, evidence, review, and coverage. |
| `PUT /me/recommendations/{session_id}/selection` | Approved plus CSRF | Freezes selected order, playlist name, and visibility. |
| `POST /me/recommendations/{session_id}/playlist` | Approved plus CSRF | Idempotently creates the reviewed playlist in the signed-in Spotify account. |
| `POST /me/recommendations/{session_id}/feedback` | Approved plus CSRF | Idempotently records an item event and applies supported account preferences. |
| `GET /me/recommendations/{session_id}/evaluation` | Approved session | Reads the owned session evaluation. |
| `PUT /me/recommendations/{session_id}/evaluation` | Approved plus CSRF | Upserts the frozen beta comparison and ratings. |
| `GET /me/preferences` | Approved session | Lists explicit-content and blocked-entity preferences. |
| `DELETE /me/preferences/artists/{artist_mbid}` | Approved plus CSRF | Removes one blocked artist preference. |

OpenAPI is intentionally disabled in production. Pydantic request models, route tests, frontend Zod
schemas, and this reference form the maintained contract.

### Recommendation Request

```http
POST /api/me/recommendations
Content-Type: application/json
```

```json
{
  "prompt": "Atmospheric trip hop for late-night focus",
  "adventure": "balanced",
  "allow_explicit": false,
  "seed_ids": ["<application-seed-uuid>"]
}
```

The prompt is 2-500 characters, `adventure` is `familiar`, `balanced`, or `adventurous`, and one to
five owned seed UUIDs are required. Unknown fields are rejected. Recommendation generation does not
write to Spotify and there is no `create_playlist` field.

The response contains the session ID and status, normalized controls and intent, selected seed IDs,
source coverage, `ranking_version`, timestamps, review state, and ordered recommendation items.
Each item contains a MusicBrainz recording MBID, attributed Spotify display mapping, selected/review
state, and a structured evidence object.

### Review And Export Contract

Review freezes user intent before an external write:

```http
PUT /api/me/recommendations/{session_id}/selection
```

```json
{
  "recording_mbids": ["<recommended-recording-mbid>"],
  "playlist_name": "Late Night Outside the Loop",
  "public": false
}
```

The user selects one to ten recommended recording MBIDs. Export must repeat the frozen name,
visibility, and ordered MBIDs and must include an `Idempotency-Key`:

```http
POST /api/me/recommendations/{session_id}/playlist
Idempotency-Key: <stable-key-for-this-logical-export>
```

```json
{
  "name": "Late Night Outside the Loop",
  "description": "Created from reviewed Outside the Loop recommendations",
  "public": false,
  "recording_mbids": ["<reviewed-recording-mbid>"]
}
```

The initial successful export returns `201`. Replaying the identical key and payload returns `200`
with `idempotent_replay: true`. Reusing the key for a different payload returns `409`. The service
persists partial progress, so retrying can resume item addition without silently creating another
playlist.

### Error Shape

Handled API failures use:

```json
{
  "detail": "Human-readable bounded message.",
  "code": "stable_machine_code"
}
```

| Status | Typical meaning |
| --- | --- |
| `400` | Invalid selection, cursor, feedback, return path, or deletion confirmation. |
| `401` | Missing/expired application session or failed OAuth completion. |
| `403` | Pending/revoked access, Origin/CSRF failure, or Spotify permission denial. |
| `404` | Unknown or cross-account resource. |
| `409` | Review/idempotency conflict or Spotify reconnection required. |
| `422` | Pydantic schema validation or forbidden extra field. |
| `502` | Invalid upstream Spotify response. |
| `503` | Database, queue, credential service, Spotify, or discovery source unavailable. |

Responses include `X-Request-ID`. Logs use a keyed, non-reversible account correlation value and do
not include cookies, OAuth codes, tokens, prompts, comments, or provider payloads.

## Backend Design

### Entry Points

| Module | Responsibility |
| --- | --- |
| `api/product_lambda_handler.py` | Mangum adapter for the product API Lambda. |
| `api/product_app.py` | FastAPI construction, middleware, health routes, and product routers. |
| `api/product_runtime.py` | Dependency graph for repositories, services, source clients, KMS, and SQS. |
| `api/discovery_worker_handler.py` | Validates SQS records and runs account-scoped discovery work. |
| `api/cleanup_handler.py` | Enforces retention in bounded daily batches. |

### Layers

1. **HTTP boundary:** `api/routes/`, `api/models.py`, dependencies, and exception handlers validate
   transport inputs and enforce session, approval, Origin, and CSRF requirements.
2. **Application services:** `product/` owns seed replacement, job lifecycle, deterministic
   recommendation snapshots, review, playlist export, feedback/evaluation, and deletion rules.
3. **Domain logic:** `recommender/` and `agents/intent.py` own intent parsing, eligibility, ranking,
   evidence validation, and deterministic ordering.
4. **External adapters:** `sources/` owns bounded MusicBrainz, ListenBrainz, and Spotify HTTP clients.
5. **Persistence:** repository protocols define contracts; `postgres_repositories.py` implements
   them with parameterized SQL and account-scoped transactions.

FastAPI dependencies inject the authenticated account and service. Route handlers do not construct
repositories or accept user-selected ownership context.

### Supabase Persistence

The production DSN is read from AWS Secrets Manager and connects through TLS using a restricted
runtime database role. The schema groups are:

- Identity: `app_users`, `oauth_states`, and `app_sessions`.
- Music and source data: `music_entities`, `source_cache_entries`, `source_rate_limits`,
  `candidate_edges`, and `external_id_mappings`.
- User input: `user_seeds` and `user_preferences`.
- Workflow state: `discovery_jobs`, `recommendation_sessions`, and `recommendation_items`.
- Outcomes: `feedback_events`, `playlist_exports`, and `session_evaluations`.

Database constraints and transactional functions enforce one-time OAuth state, five approved users,
one to five active seeds, unique idempotency keys, ownership relationships, and cascading account
deletion. The runtime role has only the schema/table/sequence/function access required by the
application; it is not the Supabase owner role.

### Queue And External Integrations

Seed search calls MusicBrainz synchronously with a contactable user agent and a distributed
one-request-per-second reservation. Discovery jobs enter an encrypted FIFO SQS queue. The worker
claims each job, calls cached or live ListenBrainz Core endpoints, stores normalized entities and
candidate edges, and reports `ready`, `degraded`, or `failed`. Retryable work is attempted at most
three times before the message reaches the dead-letter queue.

Spotify is called during OAuth, post-ranking display/export mapping, and explicit playlist export.
The current account's encrypted refresh token is decrypted only inside the relevant Lambda. Source
timeouts, retry budgets, cache TTLs, and output sizes are bounded.

### Deployment Configuration

Backend-only values include:

```text
SPOTIFY_APP_CLIENT_ID
SPOTIFY_APP_CLIENT_SECRET
SPOTIFY_REDIRECT_URI
SPOTIFY_PRODUCT_SCOPES
SUPABASE_DB_URL
SPOTIFY_TOKEN_KMS_KEY_ID
OBSERVABILITY_HASH_KEY
MUSICBRAINZ_CONTACT_EMAIL
DISCOVERY_QUEUE_URL
APP_BASE_URL
AUTH_ALLOWED_ORIGINS
```

Secrets are synchronized to `music-recommender/product/runtime` in AWS Secrets Manager and resolved
into Lambda configuration during deployment. They must never use a `VITE_*` name or enter a frontend
bundle. The product app remains session-authenticated even while the deployment parameter retains
the temporary `hybrid` rollout value; no product route accepts `X-API-Key`.

## Frontend Design

The frontend is React 19 and TypeScript built with Vite. React Router owns navigation, React Query
owns server-state fetching and mutation invalidation, Zod validates every successful API response,
and Lucide supplies interface icons. There is no frontend database SDK and no frontend Spotify SDK
with privileged credentials.

### Authentication State Machine

`AuthProvider` loads `GET /api/auth/me` with cookies on startup:

```text
401
  -> login page

authenticated + pending/revoked
  -> access status page

approved + reconnect required
  -> Spotify reconnect page

approved + no seeds
  -> seed onboarding

approved + seeds
  -> application routes
```

The public privacy page remains reachable without a session. Approval can be rechecked without a
new OAuth exchange because `/auth/me` reads current database status.

### Application Routes

| Route | UI responsibility |
| --- | --- |
| `/discover` | Prompt/adventure controls, discovery readiness, and recommendation generation. |
| `/seeds` | Search, select, order, and replace MusicBrainz seeds. |
| `/sessions/:sessionId` | Recommendation evidence and item feedback. |
| `/sessions/:sessionId/review` | Reorder/remove items, name the playlist, choose visibility, export. |
| `/history` | Cursor-backed prior-session list. |
| `/settings` | Preferences, blocked artists, privacy, logout, and deletion. |
| `/privacy` | Public and authenticated privacy notice. |

`api/client.ts` always requests relative `/api` paths with `credentials: include`. For mutations it
reads and decodes the CSRF cookie and sends `X-CSRF-Token`. The Vercel same-origin request supplies
the matching `Origin`. A non-2xx response becomes `ApiError(status, code)`; a successful response
that fails its Zod schema becomes `502 invalid_response` in the client rather than entering UI state.

### Vercel Boundary

`web/vercel.mjs` requires server-only `PRODUCT_API_ORIGIN`, rewrites `/api/:path*` to API Gateway,
and rewrites all other paths to `index.html`. It also sets CSP, HSTS, frame, MIME-sniffing, referrer,
and permissions headers. API responses are marked private and non-cacheable.

Only `VITE_OAUTH_ENABLED` is exposed at build time. Preview deployments can disable OAuth because a
Spotify redirect URI is tied to an exact stable origin.

## Development And Validation

Backend and documentation contract checks:

```bash
uv sync --all-groups --frozen
uv run ruff format --check src tests scripts/audit_beta_sources.py
uv run ruff check src tests scripts/audit_beta_sources.py
uv run mypy src tests scripts/audit_beta_sources.py
uv run pytest -q
```

Database checks use the local Supabase stack, never production:

```bash
supabase start
supabase db reset
supabase db lint --local --level warning
supabase test db
```

Frontend checks:

```bash
npm --prefix web ci
npm --prefix web run lint
npm --prefix web run typecheck
npm --prefix web run test -- --run
npm --prefix web run build
npm --prefix web run test:e2e
```

AWS packaging checks reject secrets and data files:

```bash
bash scripts/prepare_lambda_build.sh
sam validate --lint --template-file infra/template.yaml
sam build --template-file infra/template.yaml
bash scripts/prune_lambda_artifacts.sh
```

## Related Operational Documents

- [`api-usage-runbook.md`](api-usage-runbook.md): complete browser, curl, and Postman workflow.
- [`aws-deployment-architecture-runbook.md`](aws-deployment-architecture-runbook.md): AWS topology,
  trust boundaries, resources, and recovery.
- [`operational-aws-runbook.md`](operational-aws-runbook.md): migration, secrets, deployment,
  approval, alarms, incidents, and rollback.
- [`vercel-deployment-runbook.md`](vercel-deployment-runbook.md): frontend deployment and rewrite
  verification.
- [`privacy-notice.md`](privacy-notice.md): user-facing data and deletion commitments.
