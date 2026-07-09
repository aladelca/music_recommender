#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

STACK_NAME="${STACK_NAME:-music-recommender-demo}"
AWS_REGION_VALUE="${AWS_REGION_VALUE:-${AWS_REGION:-${AWS_DEFAULT_REGION:-us-east-1}}}"
DATA_BUCKET_NAME="${DATA_BUCKET_NAME:-${MUSIC_RECOMMENDER_BUCKET:-}}"
CATALOG_RUN_ID="${CATALOG_RUN_ID:-${RECOMMENDER_CATALOG_RUN_ID:-}}"
INTERACTION_RUN_ID="${INTERACTION_RUN_ID:-${RECOMMENDER_INTERACTION_RUN_ID:-}}"
DATA_PREFIX="${DATA_PREFIX:-}"
RUNTIME_SECRET_NAME="${RUNTIME_SECRET_NAME:-music-recommender/demo/runtime}"
AWS_SECRETS_PREFIX_VALUE="${AWS_SECRETS_PREFIX:-music-recommender/demo/}"
SPOTIFY_DEMO_USER_ID_VALUE="${SPOTIFY_DEMO_USER_ID:-12175364859}"
OPENAI_AGENT_MODEL_VALUE="${OPENAI_AGENT_MODEL:-}"

for required_command in uv aws jq sam; do
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

if [[ -z "${INTERACTION_RUN_ID}" ]]; then
  echo "INTERACTION_RUN_ID or RECOMMENDER_INTERACTION_RUN_ID is required." >&2
  exit 2
fi

if ! aws s3api head-bucket --bucket "${DATA_BUCKET_NAME}" >/dev/null 2>&1; then
  echo "Data bucket is not accessible: ${DATA_BUCKET_NAME}" >&2
  exit 2
fi

readiness_json="$(uv run music-recommender-demo-readiness check-s3-data \
  --bucket "${DATA_BUCKET_NAME}" \
  --catalog-run-id "${CATALOG_RUN_ID}" \
  --profile-run-id "${INTERACTION_RUN_ID}")"
if ! jq -e '.catalog.ready == true and .profile.ready == true' \
  >/dev/null <<<"${readiness_json}"; then
  echo "Catalog/profile S3 data is not ready for deployment." >&2
  exit 2
fi

if ! aws secretsmanager describe-secret \
  --region "${AWS_REGION_VALUE}" \
  --secret-id "${RUNTIME_SECRET_NAME}" \
  >/dev/null; then
  echo "Secrets Manager secret is required before deploy: ${RUNTIME_SECRET_NAME}" >&2
  exit 2
fi

bash scripts/prepare_lambda_build.sh
sam validate --lint --template-file infra/template.yaml
sam build --template-file infra/template.yaml
bash scripts/prune_lambda_artifacts.sh
MAX_LAMBDA_UNZIPPED_KB=262144
for function_name in \
  MusicRecommenderApiFunction \
  MusicRecommenderProfileSyncFunction; do
  artifact_dir=".aws-sam/build/${function_name}"
  artifact_size_kb="$(du -sk "$artifact_dir" | awk '{print $1}')"
  if (( artifact_size_kb >= MAX_LAMBDA_UNZIPPED_KB )); then
    printf '%s is too large for Lambda: %s KB (limit: %s KB).\n' \
      "$function_name" \
      "$artifact_size_kb" \
      "$MAX_LAMBDA_UNZIPPED_KB" >&2
    exit 2
  fi
  printf '%s package size: %s KB.\n' "$function_name" "$artifact_size_kb"
done

parameter_overrides=(
  "StageName=\$default"
  "DataBucketName=${DATA_BUCKET_NAME}"
  "CatalogRunId=${CATALOG_RUN_ID}"
  "InteractionRunId=${INTERACTION_RUN_ID}"
  "AwsSecretsPrefix=${AWS_SECRETS_PREFIX_VALUE}"
  "RuntimeSecretName=${RUNTIME_SECRET_NAME}"
  "SpotifyDemoUserId=${SPOTIFY_DEMO_USER_ID_VALUE}"
)
if [[ -n "$DATA_PREFIX" ]]; then
  parameter_overrides+=("DataPrefix=${DATA_PREFIX}")
fi
if [[ -n "$OPENAI_AGENT_MODEL_VALUE" ]]; then
  parameter_overrides+=("OpenAIAgentModel=${OPENAI_AGENT_MODEL_VALUE}")
fi

sam deploy \
  --stack-name "${STACK_NAME}" \
  --region "${AWS_REGION_VALUE}" \
  --template-file .aws-sam/build/template.yaml \
  --capabilities CAPABILITY_IAM \
  --resolve-s3 \
  --no-confirm-changeset \
  --no-fail-on-empty-changeset \
  --parameter-overrides "${parameter_overrides[@]}"

api_url="$(aws cloudformation describe-stacks \
  --region "${AWS_REGION_VALUE}" \
  --stack-name "${STACK_NAME}" \
  --query 'Stacks[0].Outputs[?OutputKey==`ApiUrl`].OutputValue | [0]' \
  --output text)"
echo "SAM deploy finished for stack ${STACK_NAME} in ${AWS_REGION_VALUE}: ${api_url}"
