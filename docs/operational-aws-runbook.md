# Product Operations Runbook

This runbook provisions and operates the Outside the Loop beta on Supabase, AWS, and Vercel. The
default AWS stack is `outside-the-loop-beta`. Product deployments must keep
`DEPLOY_LEGACY_DEMO=false`; no S3 dataset is required or permitted.

## Required Access And Tools

- Supabase project-owner access and Supabase CLI.
- AWS CLI access through IAM Identity Center or a scoped deployment role, plus AWS SAM CLI.
- Vercel project access and Spotify developer-dashboard access.
- `uv`, `jq`, `curl`, Node/npm, Docker, and OpenSSL.
- A contact email that can identify the application to MusicBrainz/ListenBrainz and receive SNS
  alarm confirmations.

Do not deploy with AWS root access keys. CI uses GitHub OIDC and `AWS_DEPLOY_ROLE_ARN`; local
operators should use a short-lived AWS profile.

## 1. Local Release Gate

Run this before touching production:

```bash
uv sync --all-groups --frozen
supabase start
supabase db reset
supabase db lint --local --level warning
supabase test db
TEST_SUPABASE_DB_URL=postgresql://postgres:postgres@127.0.0.1:55432/postgres \
  uv run pytest tests/integration -q
uv run ruff format --check src tests scripts/audit_beta_sources.py
uv run ruff check src tests scripts/audit_beta_sources.py
uv run mypy src tests scripts/audit_beta_sources.py
uv run pytest -q

npm --prefix web ci
npm --prefix web audit --audit-level=high
npm --prefix web run lint
npm --prefix web run typecheck
npm --prefix web run test -- --run
npm --prefix web run build
npm --prefix web run test:e2e

bash scripts/prepare_lambda_build.sh
sam validate --lint --template-file infra/template.yaml
sam build --template-file infra/template.yaml
bash scripts/prune_lambda_artifacts.sh
```

Inspect `.aws-sam/build/OutsideTheLoop*`: no `.env`, `.csv`, `.parquet`, local catalog, or S3 data
reader configuration may be present.

## 2. Provision And Migrate Supabase

Create a production Supabase project in the chosen region. Enable the backup/PITR option available
for the project plan before inviting testers. Record the project ref in a private operator
environment, then link without committing generated credentials:

```bash
export SUPABASE_PROJECT_REF='<project-ref>'
supabase link --project-ref "$SUPABASE_PROJECT_REF"
supabase db push --linked --dry-run
supabase db push --linked
```

Do not use `--include-seed`; the product has no seeded tester or recommendation records. Verify
migrations and browser-role denial:

```bash
supabase db lint --linked --level warning
```

The migrations create `outside_loop_runtime` as `NOLOGIN`. It can bypass RLS for backend system
jobs, but it has only DML on product tables, sequence use, the OAuth-state function, and read-only
migration metadata. It cannot create schema objects, databases, roles, or replication slots. Turn
on login and set a generated password through an administrative direct/session-pooler connection;
the `\password` prompt does not echo the value:

```text
psql "$SUPABASE_ADMIN_URL"
ALTER ROLE outside_loop_runtime LOGIN;
\password outside_loop_runtime
```

Build the serverless transaction-pooler DSN with the custom role and port `6543`:

```text
postgresql://outside_loop_runtime.<project-ref>:<url-encoded-password>@aws-0-<region>.pooler.supabase.com:6543/postgres?sslmode=require&gssencmode=disable
```

Store this only as `SUPABASE_DB_URL` in the ignored root `.env` and AWS Secrets Manager. The
Postgres adapter disables prepared statements because Supavisor transaction mode does not support
them. Do not use the `postgres` owner DSN for runtime traffic, and do not put any Supabase URL/key
in `web/`, Vercel, or a `VITE_*` variable.

Before every schema release:

1. Confirm a restorable backup or PITR point.
2. Run `supabase db push --linked --dry-run` and review the exact migration set.
3. Apply forward-only additive migrations before deploying code that depends on them.
4. Let `scripts/deploy_api_sam.sh` run its migration-history and connectivity preflight.
5. For recovery, restore Supabase to a new project/branch and validate it before changing the AWS
   DSN. Do not improvise a destructive down migration in production.

## 3. Prepare Product Secrets

The ignored root `.env` needs these backend values:

```text
SPOTIFY_APP_CLIENT_ID=<Spotify app client ID>
SPOTIFY_APP_CLIENT_SECRET=<Spotify app client secret>
SUPABASE_DB_URL=<TLS transaction-pooler DSN>
OBSERVABILITY_HASH_KEY=<random 32-512 character value>
```

Generate the observability HMAC key once and keep it stable across normal deploys so operational
correlations remain comparable:

```bash
openssl rand -base64 48
```

Place the generated value in `.env` without echoing it later. Sync all four values by stdin; the
script prints only the secret name, region, and action:

```bash
AWS_REGION_VALUE=us-east-1 \
RUNTIME_SECRET_NAME=music-recommender/product/runtime \
bash scripts/sync_runtime_secret.sh
```

Never run shell tracing around this script. A secret version update alone does not update Lambda's
resolved environment; redeploy the stack afterward.

## 4. Reserve The Vercel Origin And Configure Spotify

Create/link the Vercel project with root directory `web` before AWS deployment so its stable
production origin is known. Set the Spotify redirect URI to exactly:

```text
https://<project>.vercel.app/api/auth/spotify/callback
```

In Spotify Development Mode, add only the intended tester accounts. Application approval and the
internal five-user allowlist are separate controls; both must allow a tester.

See [vercel-deployment-runbook.md](vercel-deployment-runbook.md) for the complete frontend sequence.

## 5. Deploy AWS

Validate the active identity without displaying credentials:

```bash
aws sts get-caller-identity
```

Deploy the product-only stack in compatibility mode first:

```bash
export STACK_NAME=outside-the-loop-beta
export AWS_REGION_VALUE=us-east-1
export APP_BASE_URL=https://<project>.vercel.app
export MUSICBRAINZ_CONTACT_EMAIL=<operator-contact@example.com>
export PRODUCT_RUNTIME_SECRET_NAME=music-recommender/product/runtime
export PRODUCT_AUTH_MODE=hybrid
export DEPLOY_LEGACY_DEMO=false
export ENABLE_RESERVED_CONCURRENCY=false
export SAM_ARTIFACT_BUCKET=outside-the-loop-sam-<account-id>-us-east-1
export CLOUDFORMATION_EXECUTION_ROLE_ARN=arn:aws:iam::<account-id>:role/outside-the-loop-cloudformation
bash scripts/deploy_api_sam.sh
```

The wrapper verifies the runtime-secret shape without printing values, checks production migration
history/connectivity, builds isolated artifacts, rejects Parquet/CSV/`.env`, enforces package size,
validates SAM, and deploys CloudFormation.

Accounts with the default 10-concurrency Lambda quota must keep
`ENABLE_RESERVED_CONCURRENCY=false`; API Gateway throttling, SQS `MaximumConcurrency=2`, and bounded
Postgres pools still constrain load. After AWS raises the regional quota above 18, deploy with
`ENABLE_RESERVED_CONCURRENCY=true` to reserve 5/2/1 executions while retaining 10 unreserved.

Run the unauthenticated/redacted smoke suite:

```bash
STACK_NAME=outside-the-loop-beta \
AWS_REGION_VALUE=us-east-1 \
bash scripts/smoke_test_deployed_api.sh
```

It checks `/health`, database `/ready`, rejected unauthenticated product routes, Spotify OAuth
redirect, disabled legacy routes, and an empty dead-letter queue. It does not create a playlist or
read a secret.

Confirm the SNS subscription email generated by the stack. Until it is confirmed, CloudWatch
alarms are visible but do not notify the operator.

## 6. Approve Up To Five Testers

A first Spotify login creates a pending account. Run the CLI against the production DSN from a
trusted operator environment; output contains account IDs/status only and never token ciphertext:

```bash
AUTH_MODE=api_key uv run outside-the-loop-beta-admin pending
AUTH_MODE=api_key uv run outside-the-loop-beta-admin status
AUTH_MODE=api_key uv run outside-the-loop-beta-admin approve '<spotify-account-id>'
AUTH_MODE=api_key uv run outside-the-loop-beta-admin revoke '<spotify-account-id>'
AUTH_MODE=api_key uv run outside-the-loop-beta-admin evaluations
```

`outside-the-loop-beta-admin approve` is transactionally capped at five approved, non-deleted
accounts. Revocation removes refresh-token ciphertext and revokes active sessions. Do not maintain
a second allowlist in a file or S3.

After owner acceptance and at least one second-account isolation test, redeploy with:

```bash
PRODUCT_AUTH_MODE=spotify_session bash scripts/deploy_api_sam.sh
```

Keep `hybrid` available only as a temporary application rollback mode; the product Lambda itself
still exposes only product routes.

## Monitoring

List stack outputs and alarm state:

```bash
aws cloudformation describe-stacks \
  --region "$AWS_REGION_VALUE" --stack-name "$STACK_NAME" \
  --query 'Stacks[0].{Status:StackStatus,Outputs:Outputs}' --output json | jq .

aws cloudwatch describe-alarms \
  --region "$AWS_REGION_VALUE" --alarm-name-prefix "$STACK_NAME" \
  --query 'MetricAlarms[].{Name:AlarmName,State:StateValue,Reason:StateReason}' \
  --output table
```

The stack alarms on Lambda errors, handled API 5xx responses, p95 duration, database readiness,
ListenBrainz/source failures, Spotify reconnect spikes, cleanup failures, queue age, and any DLQ
message. EMF metrics also include route latency, recommendation source/evidence coverage, cache
hits/misses, playlist outcomes, queue age, and cleanup counts.

Tail structured logs without expanding request bodies:

```bash
API_FUNCTION="$(aws cloudformation describe-stacks \
  --region "$AWS_REGION_VALUE" --stack-name "$STACK_NAME" \
  --query 'Stacks[0].Outputs[?OutputKey==`ProductApiFunctionName`].OutputValue|[0]' \
  --output text)"
aws logs tail "/aws/lambda/$API_FUNCTION" --region "$AWS_REGION_VALUE" --since 15m
```

Use `request_id`, route template, status, latency, and HMAC `user_correlation` for incidents. Never
add prompt/body, Cookie, Authorization, raw account ID, OAuth code, token, provider payload, or
evaluation comment to a ticket.

## Dead-Letter Queue Response

Any visible dead-letter queue message is an incident:

1. Stop new discovery if failures are systematic by setting API reserved concurrency to zero or
   disabling the affected adapter through a controlled deployment.
2. Inspect CloudWatch events by SQS message ID; do not paste message bodies into tickets because
   they contain internal account/job IDs.
3. Fix the database/source/configuration cause and deploy.
4. Redrive only after proving the worker remains idempotent; otherwise leave the message for manual
   reconciliation.
5. Confirm queue age, DLQ depth, job state, and source-failure alarms return to `OK`.

## Spotify Reconnect And Secret Rotation

- Spotify `401` marks the account for reconnect; the user signs in again and a rotated refresh
  token replaces ciphertext transactionally.
- Rotate the Spotify client secret or Supabase password in the provider first, update ignored
  `.env`, run `sync_runtime_secret.sh`, redeploy, and smoke test.
- For a Supabase rotation, use `\password outside_loop_runtime`, replace only the password in the
  port-6543 DSN, verify a transaction-pooler connection, then sync and redeploy. The scoped AWS
  deployment role can write only the named product runtime secret.
- Rotate `OBSERVABILITY_HASH_KEY` only for a security reason; rotation intentionally breaks
  correlation continuity.
- KMS automatic rotation does not require rewriting ciphertext. If replacing the KMS key, deploy a
  controlled re-encryption migration before retiring the old key.

## Account Deletion And Retention

Users delete their own account with exact confirmation `DELETE`. The transaction cascades sessions,
token ciphertext, seeds, preferences, recommendation/evidence, feedback, exports, and evaluations.
The daily cleanup Lambda removes expired OAuth state, sessions, caches, mappings, jobs, removed
seeds, and retained recommendation records in bounded batches. Existing Spotify playlists remain
owned by the user and must be deleted in Spotify if desired.

## Rollback

Application rollback:

1. Keep the database migration in place if it is backward compatible.
2. Check out the last known-good commit and rerun `scripts/deploy_api_sam.sh` with the same Vercel
   origin, secret name, and `DEPLOY_LEGACY_DEMO=false`.
3. Roll Vercel back to the matching frontend deployment.
4. Run both smoke scripts and one authenticated owner flow.

Database rollback:

1. Stop product writes by setting product Lambda reserved concurrency to zero.
2. Restore the verified Supabase backup/PITR point to a separate project.
3. Run migration and ownership/security tests against the restored database.
4. Update only `SUPABASE_DB_URL`, sync the secret, redeploy, and re-enable traffic.

Do not switch product reads to DynamoDB, local files, S3, CSV, or Parquet during an incident. If
safe service cannot be restored, leave `/ready` unavailable and communicate the outage.

## Cost And Capacity

The five-user beta uses on-demand API Gateway/Lambda/SQS/SNS, one customer KMS key, Secrets Manager,
CloudWatch logs/alarms, Supabase, and Vercel. Reserved Lambda concurrency bounds database/source
load. Review Supabase connection counts, CloudWatch log retention, alarms, queue age, and monthly
spend before expanding beyond five approved users.
