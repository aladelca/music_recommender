# AWS Serverless Deployment

This deploys the backend-only class demo through AWS Lambda and API Gateway. Extracted catalog and
profile datasets live in S3; runtime API state uses DynamoDB for profile cache, recommendation
sessions, playlist idempotency, and feedback events.

## Resources

- API Gateway HTTP API
- Lambda function running `music_recommender.api.lambda_handler.handler`
- Scheduled Lambda function refreshing the configured Spotify profile cache every day
- EventBridge schedule with a configurable expression
- DynamoDB tables for demo users/profile cache, recommendation sessions, playlist records, and
  feedback events, with point-in-time recovery, encryption, and retention on stack deletion
- S3 read permissions for extracted recommender data
- Secrets Manager read permission scoped by `AWS_SECRETS_PREFIX`
- CloudWatch API access logs, Lambda log retention, and Lambda error alarms

## Prerequisites

- AWS credentials configured for the target account
- AWS SAM CLI installed
- A deployed or bootstrapped recommender data bucket
- An ignored `.env` containing the Spotify/OpenAI runtime values

Create or update the JSON runtime secret without placing secret values in shell history:

```bash
AWS_REGION_VALUE=us-east-1 \
RUNTIME_SECRET_NAME=music-recommender/demo/runtime \
bash scripts/sync_runtime_secret.sh
```

The script preserves an existing `RECOMMENDER_API_KEY`, generates a strong one when absent, and
never prints the secret payload. Deploy again after changing the secret because CloudFormation
resolves the secret values into Lambda environment variables during a stack update.

## Build And Deploy

From the repository root:

```bash
STACK_NAME=music-recommender-demo \
AWS_REGION_VALUE=us-east-1 \
DATA_BUCKET_NAME=<your-music-recommender-bucket> \
CATALOG_RUN_ID=<catalog-run-id> \
INTERACTION_RUN_ID=<profile-run-id> \
RUNTIME_SECRET_NAME=music-recommender/demo/runtime \
bash scripts/deploy_api_sam.sh
```

Suggested guided values:

```text
Stack Name: music-recommender-demo
AWS Region: us-east-1
Parameter DataBucketName: <your-music-recommender-bucket>
Parameter DataPrefix: <optional-prefix-containing-silver-gold-metadata/>
Parameter CatalogRunId: <catalog-run-id>
Parameter InteractionRunId: <profile-run-id>
Parameter RuntimeSecretName: music-recommender/demo/runtime
Parameter AwsSecretsPrefix: music-recommender/demo/
Parameter ProfileSyncScheduleExpression: cron(0 10 * * ? *)
```

After deployment, run the redacted end-to-end smoke suite. It retrieves the API URL and API key
from AWS, tests authentication and every route, and creates one private Spotify smoke playlist:

```bash
STACK_NAME=music-recommender-demo \
AWS_REGION_VALUE=us-east-1 \
bash scripts/smoke_test_deployed_api.sh
```

## Upload Existing Local Runs

When a local run is already present under `data/local/<run-id>/`, upload it to the bucket root:

```bash
MUSIC_RECOMMENDER_BUCKET=<your-music-recommender-bucket> \
bash scripts/upload_local_run_to_s3.sh <catalog-run-id>
```

The recommender S3 reader expects promoted `silver` and `gold` datasets at the bucket root and
filters rows by `source_run_id`.

The deployment script prepares ignored, function-specific build contexts under `.lambda-build/` so
local datasets and development dependencies are never copied into Lambda artifacts. Recompile the
tracked `infra/lambda/*-requirements.txt` files from their `.in` files when runtime dependencies
change. The preparation step explicitly rejects every `.parquet` and `.csv` file; those datasets
remain in S3 and are read at runtime.

The stack retains DynamoDB tables during stack deletion or replacement. This protects runtime state
but means table cleanup is a separate, deliberate operation. See
`docs/operational-aws-runbook.md` for monitoring and rollback commands.
