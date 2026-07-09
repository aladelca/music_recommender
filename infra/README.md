# AWS Serverless Deployment

This deploys the backend-only class demo through AWS Lambda and API Gateway. Extracted catalog and
profile datasets live in S3; runtime API state uses DynamoDB for profile cache, recommendation
sessions, playlist idempotency, and feedback events.

## Resources

- API Gateway HTTP API
- Lambda function running `music_recommender.api.lambda_handler.handler`
- DynamoDB tables for demo users/profile cache, recommendation sessions, playlist records, and
  feedback events
- S3 read permissions for extracted recommender data
- Secrets Manager read permission scoped by `AWS_SECRETS_PREFIX`
- CloudWatch log retention for the Lambda function

## Prerequisites

- AWS credentials configured for the target account
- AWS SAM CLI installed
- A deployed or bootstrapped recommender data bucket
- Secrets Manager secrets under the configured prefix for OpenAI and Spotify runtime secrets

Create one JSON secret for Lambda runtime values:

```bash
aws secretsmanager create-secret \
  --name music-recommender/demo/runtime \
  --secret-string '{
    "OPENAI_API_KEY": "replace-me",
    "RECOMMENDER_API_KEY": "replace-me",
    "SPOTIFY_APP_CLIENT_ID": "replace-me",
    "SPOTIFY_APP_CLIENT_SECRET": "replace-me",
    "SPOTIFY_USER_REFRESH_TOKEN": "replace-me"
  }'
```

## Build And Deploy

From the repository root:

```bash
STACK_NAME=music-recommender-demo \
MUSIC_RECOMMENDER_BUCKET=<your-music-recommender-bucket> \
CATALOG_RUN_ID=<catalog-run-id> \
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
Parameter RuntimeSecretName: music-recommender/demo/runtime
Parameter AwsSecretsPrefix: music-recommender/demo/
```

After deployment, use the `ApiUrl` output:

```bash
curl "$API_URL/health"
curl -H "X-API-Key: $RECOMMENDER_API_KEY" "$API_URL/profile"
```

## Upload Existing Local Runs

When a local run is already present under `data/local/<run-id>/`, upload it to the bucket root:

```bash
MUSIC_RECOMMENDER_BUCKET=<your-music-recommender-bucket> \
bash scripts/upload_local_run_to_s3.sh <catalog-run-id>
```

The recommender S3 reader expects promoted `silver` and `gold` datasets at the bucket root and
filters rows by `source_run_id`.

Remove the generated top-level `requirements.txt` after deployment if you do not intend to commit
it. The source of truth for Python dependencies remains `pyproject.toml` and `uv.lock`.
