# AWS Serverless Product Stack

`infra/template.yaml` deploys Outside the Loop's AWS backend. The normal product deployment sets
`DeployLegacyDemo=false` and creates no S3 or DynamoDB data resources.

## Product Resources

- API Gateway HTTP API with bounded throttling and redacted access logs.
- `OutsideTheLoopApiFunction`, a thin FastAPI/Mangum Lambda for OAuth and product APIs.
- Customer-managed rotating KMS key for Spotify refresh tokens and OAuth PKCE verifiers.
- FIFO discovery queue and FIFO dead-letter queue.
- `OutsideTheLoopDiscoveryWorkerFunction` for automated ListenBrainz Core API expansion.
- `OutsideTheLoopCleanupFunction` on a daily EventBridge schedule.
- 30-day Lambda/API log groups, CloudWatch/Lambda/SQS/EMF alarms, and an encrypted SNS topic with an
  operator email subscription.

Supabase Postgres is provisioned outside this template and reached through a TLS transaction-pooler
DSN stored in Secrets Manager. Runtime connections use the migration-defined
`outside_loop_runtime` role, not the `postgres` owner. Vercel is provisioned separately and
rewrites browser `/api/*` calls to the `ProductApiUrl` output.

Product functions have no S3 environment variables, no S3 IAM actions, and no local catalog input.
Their scoped requirements exclude PyArrow, OpenAI, Pandas, and NumPy.

## Required Parameters

| Parameter | Example | Purpose |
| --- | --- | --- |
| `ProductAuthMode` | `hybrid` then `spotify_session` | Compatibility rollout/auth enforcement |
| `AppBaseUrl` | `https://outside-the-loop.vercel.app` | Cookie Origin and Spotify callback origin |
| `ProductRuntimeSecretName` | `music-recommender/product/runtime` | Backend-only credential JSON |
| `MusicBrainzContactEmail` | operator email | Source User-Agent and SNS subscription |
| `SpotifyMarket` | `US` | Post-ranking Spotify lookup market |
| `DeployLegacyDemo` | `false` | Must remain false for the product |

The runtime secret must contain `SPOTIFY_APP_CLIENT_ID`, `SPOTIFY_APP_CLIENT_SECRET`,
`SUPABASE_DB_URL`, and `OBSERVABILITY_HASH_KEY`.

## Build And Validate

From the repository root:

```bash
bash scripts/prepare_lambda_build.sh
sam validate --lint --template-file infra/template.yaml
sam build --template-file infra/template.yaml
bash scripts/prune_lambda_artifacts.sh
```

Five isolated build contexts are created for legacy API, legacy profile sync, product API,
discovery worker, and cleanup. Preparation/pruning rejects `.parquet`, `.csv`, and `.env` anywhere
in an artifact. Product artifacts must remain below 128 MiB unzipped; every Lambda must remain below
AWS's 256 MiB limit.

## Deploy

Use the wrapper rather than raw `sam deploy` so database migration preflight and package policy run:

```bash
STACK_NAME=outside-the-loop-beta \
AWS_REGION_VALUE=us-east-1 \
APP_BASE_URL=https://<project>.vercel.app \
MUSICBRAINZ_CONTACT_EMAIL=<operator@example.com> \
PRODUCT_RUNTIME_SECRET_NAME=music-recommender/product/runtime \
PRODUCT_AUTH_MODE=hybrid \
DEPLOY_LEGACY_DEMO=false \
bash scripts/deploy_api_sam.sh
```

Then run:

```bash
STACK_NAME=outside-the-loop-beta \
AWS_REGION_VALUE=us-east-1 \
bash scripts/smoke_test_deployed_api.sh
```

Safe outputs include product API/function names, queue/DLQ URLs, and KMS ARN. Confirm the SNS email
subscription after first deployment.

## IAM Boundary

The product API can encrypt/decrypt only with the stack token key and send only to the discovery
queue. The SQS event mapping grants the worker queue-consume access. Database credentials arrive as
deployment-time Secrets Manager dynamic references. Product functions do not receive
`secretsmanager:GetSecretValue` or any `s3:*` action.

GitHub deployment uses OIDC in `.github/workflows/deploy-aws.yml`; configure a scoped
`AWS_DEPLOY_ROLE_ARN` repository/environment variable and require production approval. Do not store
long-lived AWS access keys in GitHub.

`infra/deployment-role-template.yaml` bootstraps the GitHub OIDC provider, private versioned SAM
artifact bucket, deployment role, and separate CloudFormation execution role. Configure its safe
outputs as `AWS_DEPLOY_ROLE_ARN`, `AWS_SAM_ARTIFACT_BUCKET`, and
`AWS_CLOUDFORMATION_EXECUTION_ROLE_ARN`. The deployment role can put versions only on the named
product runtime secret, which supports credential rotation without a root deployment.

## Legacy Condition

The old `MusicRecommender*` API, profile scheduler, DynamoDB tables, S3 configuration, and legacy
alarms are all guarded by `DeployLegacy`. They exist only to preserve the educational demo and are
not a product rollback data source. Do not set `DeployLegacyDemo=true` in the five-user stack.

See [the architecture runbook](../docs/aws-deployment-architecture-runbook.md) and
[operations runbook](../docs/operational-aws-runbook.md) for trust boundaries, migration, alarms,
incidents, and rollback.
