# Outside the Loop

Outside the Loop is an explainable music-discovery beta for five Spotify testers. A tester signs
in with Spotify, explicitly chooses one to five MusicBrainz seeds, requests a discovery mood, sees
source-backed recommendation evidence, reviews the tracks, and exports a named public or private
playlist to the same Spotify account.

The active product does not inspect Spotify listening history, saved tracks, top items, or existing
playlists. Spotify is used for OAuth identity, post-ranking track lookup and attribution, and an
explicit playlist write. Recommendation data is fetched automatically from MusicBrainz and
ListenBrainz over HTTPS and cached in backend-only Supabase Postgres. The product uses no local files, S3 datasets, CSV, or Parquet as recommendation inputs or deployment artifacts.

## Product Architecture

```text
Browser
  -> Vercel React/Vite application
  -> same-origin /api rewrite
  -> AWS API Gateway HTTP API
  -> FastAPI on Lambda
       -> Supabase Postgres (accounts, sessions, caches, recommendations)
       -> MusicBrainz API (explicit seed search)
       -> SQS -> discovery Lambda -> ListenBrainz Core API
       -> Spotify OAuth/Web API (identity, lookup, playlist export)
       -> KMS (refresh-token and PKCE encryption)
```

Vercel is the public frontend edge, so CloudFront is not required. Supabase credentials and Spotify
secrets exist only in AWS. Product Lambdas have no S3 data configuration or S3 IAM permissions.
The optional old S3/DynamoDB demo is isolated behind `DeployLegacyDemo=false` by default.

The current production frontend is <https://outside-the-loop.vercel.app>. Access remains limited
to the five-account Spotify beta controls described below.

## Repository Layout

- `src/music_recommender/api/product_app.py`: product-only FastAPI application.
- `src/music_recommender/product/`: account-scoped discovery, recommendation, export, and feedback
  services.
- `src/music_recommender/sources/`: bounded MusicBrainz, ListenBrainz, and Spotify clients.
- `supabase/migrations/`: product schema, constraints, grants, and retention support.
- `web/`: React 19, TypeScript, Vite, component tests, and Playwright flows.
- `infra/template.yaml`: API, KMS, FIFO SQS/DLQ, workers, cleanup, logs, metrics, alarms, and SNS.
- `scripts/`: redacted secret sync, packaging, deployment, and smoke verification.

## Local Quality Gates

Install Python and frontend dependencies:

```bash
uv sync --all-groups --frozen
npm --prefix web ci
```

Start the local Supabase stack and apply every migration:

```bash
supabase start
supabase db reset
supabase db lint --local --level warning
supabase test db
```

Run backend and database tests:

```bash
uv run ruff format --check src tests scripts/audit_beta_sources.py
uv run ruff check src tests scripts/audit_beta_sources.py
uv run mypy src tests scripts/audit_beta_sources.py
uv run pytest -q

TEST_SUPABASE_DB_URL=postgresql://postgres:postgres@127.0.0.1:55432/postgres \
uv run pytest tests/integration -q
```

Run frontend gates:

```bash
npm --prefix web audit --audit-level=high
npm --prefix web run lint
npm --prefix web run typecheck
npm --prefix web run test -- --run
npm --prefix web run build
npm --prefix web run test:e2e
```

Validate AWS packaging. These scripts fail if `.parquet`, `.csv`, or `.env` enters a Lambda
artifact, and product artifacts must remain below 128 MiB unzipped:

```bash
bash scripts/prepare_lambda_build.sh
sam validate --lint --template-file infra/template.yaml
sam build --template-file infra/template.yaml
bash scripts/prune_lambda_artifacts.sh
```

## Product Configuration

Use `.env.example` as the field reference. Product deployment requires:

```text
SPOTIFY_APP_CLIENT_ID
SPOTIFY_APP_CLIENT_SECRET
SUPABASE_DB_URL
OBSERVABILITY_HASH_KEY
MUSICBRAINZ_CONTACT_EMAIL
APP_BASE_URL
```

`OBSERVABILITY_HASH_KEY` must be a random 32-512 character secret. Never put `SUPABASE_DB_URL`,
the Spotify client secret, refresh tokens, or the observability key in `web/` or a `VITE_*`
variable.

## Deployment

The production sequence is deliberate:

1. Provision and migrate Supabase.
2. Create the Vercel project to reserve its stable production origin.
3. Register `<vercel-origin>/api/auth/spotify/callback` in Spotify.
4. Sync the backend runtime secret and deploy the AWS product stack.
5. Set Vercel's server-only `PRODUCT_API_ORIGIN` to the API Gateway origin and deploy `web/`.
6. Run AWS and Vercel smoke checks, then approve testers through the admin CLI.

Detailed commands and rollback procedures are in the deployment runbooks below.

## Runbooks

- [API usage](docs/api-usage-runbook.md): browser-session authentication, Postman/curl examples,
  discovery, recommendations, review-first playlist export, feedback, and deletion.
- [AWS architecture](docs/aws-deployment-architecture-runbook.md): topology, trust boundaries, IAM,
  data flow, reliability, and the no-file product boundary.
- [AWS operations](docs/operational-aws-runbook.md): Supabase migration, secret sync, deployment,
  five-user approval, monitoring, incidents, rotation, and rollback.
- [Vercel deployment](docs/vercel-deployment-runbook.md): project setup, rewrite variables, Spotify
  callback configuration, headers, previews, and production verification.
- [Scientific methodology](docs/recommender-methodology-runbook.md): candidate sources, frozen
  ranking equation, evidence, coverage gates, and the five-tester evaluation protocol.
- [Privacy notice](docs/privacy-notice.md): processed data, retention, user choices, and deletion.

## Legacy Demo

The repository still contains an educational single-user pipeline and legacy API that can extract
local/S3 datasets and use DynamoDB. Those modules are not part of Outside the Loop, are not built
into the thin product functions, and deploy only when `DeployLegacyDemo=true` is explicitly set.
Do not enable that condition for the five-user product stack.
