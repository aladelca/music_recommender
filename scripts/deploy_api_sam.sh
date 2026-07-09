#!/usr/bin/env bash
set -euo pipefail

STACK_NAME="${STACK_NAME:-music-recommender-demo}"
AWS_REGION_VALUE="${AWS_REGION:-${AWS_DEFAULT_REGION:-us-east-1}}"
DATA_BUCKET_NAME="${DATA_BUCKET_NAME:-${MUSIC_RECOMMENDER_BUCKET:-}}"
CATALOG_RUN_ID="${CATALOG_RUN_ID:-${RECOMMENDER_CATALOG_RUN_ID:-}}"
INTERACTION_RUN_ID="${INTERACTION_RUN_ID:-${RECOMMENDER_INTERACTION_RUN_ID:-}}"
DATA_PREFIX="${DATA_PREFIX:-}"
RUNTIME_SECRET_NAME="${RUNTIME_SECRET_NAME:-music-recommender/demo/runtime}"
AWS_SECRETS_PREFIX_VALUE="${AWS_SECRETS_PREFIX:-music-recommender/demo/}"
SPOTIFY_DEMO_USER_ID_VALUE="${SPOTIFY_DEMO_USER_ID:-12175364859}"
OPENAI_AGENT_MODEL_VALUE="${OPENAI_AGENT_MODEL:-}"

for required_command in uv aws sam; do
  if ! command -v "${required_command}" >/dev/null 2>&1; then
    echo "${required_command} is required to deploy the API." >&2
    exit 2
  fi
done

if [[ -z "${DATA_BUCKET_NAME}" ]]; then
  echo "DATA_BUCKET_NAME or MUSIC_RECOMMENDER_BUCKET is required." >&2
  exit 2
fi

if [[ -z "${CATALOG_RUN_ID}" ]]; then
  echo "CATALOG_RUN_ID or RECOMMENDER_CATALOG_RUN_ID is required." >&2
  exit 2
fi

if ! aws secretsmanager describe-secret \
  --region "${AWS_REGION_VALUE}" \
  --secret-id "${RUNTIME_SECRET_NAME}" \
  >/dev/null; then
  echo "Secrets Manager secret is required before deploy: ${RUNTIME_SECRET_NAME}" >&2
  exit 2
fi

if [[ "${KEEP_REQUIREMENTS_TXT:-false}" != "true" ]]; then
  trap 'rm -f requirements.txt' EXIT
fi

uv export --format requirements-txt --no-hashes --output-file requirements.txt
sam build --template-file infra/template.yaml
sam deploy \
  --stack-name "${STACK_NAME}" \
  --region "${AWS_REGION_VALUE}" \
  --template-file .aws-sam/build/template.yaml \
  --capabilities CAPABILITY_IAM \
  --resolve-s3 \
  --parameter-overrides \
    StageName="\$default" \
    DataBucketName="${DATA_BUCKET_NAME}" \
    DataPrefix="${DATA_PREFIX}" \
    CatalogRunId="${CATALOG_RUN_ID}" \
    InteractionRunId="${INTERACTION_RUN_ID}" \
    AwsSecretsPrefix="${AWS_SECRETS_PREFIX_VALUE}" \
    RuntimeSecretName="${RUNTIME_SECRET_NAME}" \
    SpotifyDemoUserId="${SPOTIFY_DEMO_USER_ID_VALUE}" \
    OpenAIAgentModel="${OPENAI_AGENT_MODEL_VALUE}"

echo "SAM deploy finished for stack ${STACK_NAME} in ${AWS_REGION_VALUE}."
