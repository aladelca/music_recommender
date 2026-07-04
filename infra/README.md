# AWS Serverless Deployment

This is the Phase 4 deployment foundation for the backend-only class demo. It deploys the FastAPI
application through AWS Lambda and API Gateway, plus the demo DynamoDB tables and IAM permissions
needed by later recommendation, playlist, profile, and feedback routes.

The template is intentionally small and explainable. Phase 3 routes can be added to the same
FastAPI app without changing the public API Gateway shape.

## Resources

- API Gateway HTTP API
- Lambda function running `music_recommender.api.lambda_handler.handler`
- DynamoDB tables for demo users, recommendation sessions, and feedback events
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
uv export --format requirements-txt --no-hashes --output-file requirements.txt
sam build --template-file infra/template.yaml
sam deploy --guided --template-file .aws-sam/build/template.yaml
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

Remove the generated top-level `requirements.txt` after deployment if you do not intend to commit
it. The source of truth for Python dependencies remains `pyproject.toml` and `uv.lock`.
