# Operational AWS Runbook

This runbook operates the secured single-user music recommender backend in AWS account
`571600852509`, region `us-east-1`. It does not deploy a frontend, custom domain, or multi-user OAuth
flow.

Current deployed stack: `music-recommender-demo`. Current API URL:
`https://4bds6ddj39.execute-api.us-east-1.amazonaws.com/`.

## Architecture

- API Gateway HTTP API exposes FastAPI from Lambda.
- `X-API-Key` protects profile, recommendation, feedback, and playlist routes.
- S3 stores validated catalog and offline Spotify profile datasets.
- DynamoDB stores the live profile cache, recommendation sessions, feedback, and playlist
  idempotency records.
- Secrets Manager stores OpenAI, Spotify, and API credentials.
- EventBridge invokes a dedicated profile-sync Lambda daily at 10:00 UTC by default.
- CloudWatch retains API access and Lambda logs for 14 days and alarms on Lambda errors.

Lambda build contexts contain only application source and function-specific Python dependencies.
The build fails if a Parquet or CSV file enters either artifact; catalog/profile data remains in S3.

## Security Preconditions

Do not print or commit `.env`, OAuth responses, API keys, or Secrets Manager values. The currently
configured AWS CLI identity is the account root identity; move routine future deployments to IAM
Identity Center or a scoped deployment role and revoke root access keys after that migration.

The data bucket must keep S3 Block Public Access enabled. Protected API calls must return `401`
without `X-API-Key`; the smoke script verifies this after every deployment.

## Initial Deployment

Install the supported SAM CLI package and verify the local toolchain:

```bash
brew install aws-sam-cli
aws sts get-caller-identity
sam --version
```

Validate the Spotify refresh token and required scopes without printing it:

```bash
uv run music-recommender-demo-readiness refresh-spotify-token
uv run music-recommender-demo-readiness check-live-profile --include-playlists
```

Provision the runtime secret from the ignored `.env`:

```bash
AWS_REGION_VALUE=us-east-1 \
RUNTIME_SECRET_NAME=music-recommender/demo/runtime \
bash scripts/sync_runtime_secret.sh
```

Validate the existing S3 runs and deploy:

```bash
uv run music-recommender-demo-readiness check-s3-data \
  --bucket music-recommender-571600852509-us-east-1 \
  --catalog-run-id 20260522052343-7123c483 \
  --profile-run-id profile-20260709-live-smoke

STACK_NAME=music-recommender-demo \
AWS_REGION_VALUE=us-east-1 \
DATA_BUCKET_NAME=music-recommender-571600852509-us-east-1 \
CATALOG_RUN_ID=20260522052343-7123c483 \
INTERACTION_RUN_ID=profile-20260709-live-smoke \
bash scripts/deploy_api_sam.sh
```

## Live Validation

Run the smoke suite after initial deployment and every stack or secret update:

```bash
STACK_NAME=music-recommender-demo \
AWS_REGION_VALUE=us-east-1 \
bash scripts/smoke_test_deployed_api.sh
```

The suite verifies health/configuration, rejected unauthenticated access, live Spotify profile sync,
profile status, recommendation creation, feedback persistence, private playlist creation, and
playlist idempotency. It creates one private playlist with an `AWS Smoke` name. Set
`SMOKE_USE_OPENAI_AGENT=false` only when isolating deterministic recommendation behavior during an
OpenAI incident; normal validation exercises the OpenAI agent path.

## Scheduled Profile Refresh

The default expression is `cron(0 10 * * ? *)`. Find the generated EventBridge rule and scheduled
function through stack resources and outputs:

```bash
aws cloudformation describe-stack-resources \
  --region us-east-1 \
  --stack-name music-recommender-demo \
  --query 'StackResources[?ResourceType==`AWS::Events::Rule` || LogicalResourceId==`MusicRecommenderProfileSyncFunction`].[LogicalResourceId,PhysicalResourceId,ResourceType]' \
  --output table
```

Invoke the scheduled function directly after credential rotation, then inspect only its redacted
count response:

```bash
PROFILE_FUNCTION="$(aws cloudformation describe-stacks \
  --region us-east-1 \
  --stack-name music-recommender-demo \
  --query 'Stacks[0].Outputs[?OutputKey==`ProfileSyncFunctionName`].OutputValue | [0]' \
  --output text)"

aws lambda invoke \
  --region us-east-1 \
  --function-name "$PROFILE_FUNCTION" \
  --cli-binary-format raw-in-base64-out \
  --payload '{"source":"aws.events","detail-type":"Scheduled Event","detail":{}}' \
  /tmp/music-recommender-profile-sync.json
jq '{status, synced_at, source_counts, missing_optional_scopes}' \
  /tmp/music-recommender-profile-sync.json
```

## Monitoring

List stack alarms and inspect recent Lambda errors:

```bash
aws cloudwatch describe-alarms \
  --region us-east-1 \
  --alarm-name-prefix music-recommender-demo \
  --query 'MetricAlarms[].{Name:AlarmName,State:StateValue,Reason:StateReason}' \
  --output table

aws logs describe-log-groups \
  --region us-east-1 \
  --log-group-name-prefix /aws/lambda/music-recommender-demo \
  --query 'logGroups[].{Name:logGroupName,Retention:retentionInDays}' \
  --output table
```

The alarms have no notification subscriber because no notification endpoint is configured. Add an
SNS subscription before treating alarms as unattended paging.

## Secret Rotation

Update `.env`, run `scripts/sync_runtime_secret.sh`, validate Spotify access, and rerun the deploy
wrapper. A Secrets Manager version update alone does not replace values already resolved into
Lambda environment variables by CloudFormation.

The provisioning script preserves the current `RECOMMENDER_API_KEY`. To rotate that key, explicitly
set a new value in the existing secret through an approved secret-management workflow, redeploy,
and update clients without printing the value.

## Updating Data Runs

Catalog and offline interaction run IDs are CloudFormation parameters. Extract and validate a new
run in S3 first, then deploy with new `CATALOG_RUN_ID` and `INTERACTION_RUN_ID` values. Daily profile
sync updates DynamoDB only; it does not rewrite S3 medallion datasets.

## Rollback And Recovery

- Failed stack deployments use CloudFormation rollback. Inspect stack events before retrying.
- Revert code/template changes and rerun the deploy wrapper to restore a previous application
  version.
- Restore a previous Secrets Manager version and redeploy when credential rotation breaks runtime
  access.
- Disable the generated EventBridge rule during a Spotify outage to stop scheduled failures while
  keeping manual API sync available.
- DynamoDB point-in-time recovery can restore table state to a new table after accidental writes.
- Stack deletion retains all four DynamoDB tables. Export and delete retained tables only through a
  deliberate cleanup operation after confirming they are no longer needed.

## Cost Shape

This stack uses request-based API Gateway/Lambda, DynamoDB on-demand capacity with PITR, one Secrets
Manager secret, S3 storage/requests, EventBridge scheduling, CloudWatch logs, and two alarms. Charges
are usage-dependent; PITR, Secrets Manager, logs, and alarms can incur cost even at low traffic.

## Deployment Validation Record

On 2026-07-09, stack `music-recommender-demo` reached `UPDATE_COMPLETE`. The live validation proved:

- Public health succeeds and protected profile access returns `401` without the API key.
- Spotify profile sync reads saved/top/playlist signals and persists the cache in DynamoDB.
- OpenAI-backed recommendation returns catalog tracks and persists recommendation sessions.
- Feedback persists and one private Spotify smoke playlist was created with idempotent replay.
- Direct scheduled Lambda invocation succeeds; its EventBridge rule is enabled for
  `cron(0 10 * * ? *)`.
- All four DynamoDB tables have point-in-time recovery enabled, both Lambda alarms are `OK`, and
  Lambda/API access logs retain 14 days.
- Catalog and profile S3 readiness remains true.
- Deployment artifacts contain no Parquet or CSV files; those datasets remain in S3.
