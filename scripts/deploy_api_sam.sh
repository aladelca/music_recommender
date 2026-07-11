#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

STACK_NAME="${STACK_NAME:-outside-the-loop-beta}"
AWS_REGION_VALUE="${AWS_REGION_VALUE:-${AWS_REGION:-${AWS_DEFAULT_REGION:-us-east-1}}}"
PRODUCT_RUNTIME_SECRET_NAME="${PRODUCT_RUNTIME_SECRET_NAME:-music-recommender/product/runtime}"
APP_BASE_URL_VALUE="${APP_BASE_URL:-}"
MUSICBRAINZ_CONTACT_EMAIL_VALUE="${MUSICBRAINZ_CONTACT_EMAIL:-}"
PRODUCT_AUTH_MODE_VALUE="${PRODUCT_AUTH_MODE:-hybrid}"
SPOTIFY_MARKET_VALUE="${SPOTIFY_MARKET:-US}"
DEPLOY_LEGACY_DEMO_VALUE="${DEPLOY_LEGACY_DEMO:-false}"
ENABLE_RESERVED_CONCURRENCY_VALUE="${ENABLE_RESERVED_CONCURRENCY:-false}"
SAM_ARTIFACT_BUCKET="${SAM_ARTIFACT_BUCKET:-}"
CLOUDFORMATION_EXECUTION_ROLE_ARN="${CLOUDFORMATION_EXECUTION_ROLE_ARN:-}"

for required_command in uv aws jq sam; do
  if ! command -v "$required_command" >/dev/null 2>&1; then
    printf 'Required command is not installed: %s\n' "$required_command" >&2
    exit 2
  fi
done

if [[ ! "$APP_BASE_URL_VALUE" =~ ^https://[A-Za-z0-9.-]+(:[0-9]+)?$ ]]; then
  echo "APP_BASE_URL must be an exact HTTPS origin with no path or trailing slash." >&2
  exit 2
fi
if [[ ! "$MUSICBRAINZ_CONTACT_EMAIL_VALUE" =~ ^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$ ]]; then
  echo "MUSICBRAINZ_CONTACT_EMAIL must be a valid contact email." >&2
  exit 2
fi
if [[ "$PRODUCT_AUTH_MODE_VALUE" != "hybrid" && "$PRODUCT_AUTH_MODE_VALUE" != "spotify_session" ]]; then
  echo "PRODUCT_AUTH_MODE must be hybrid or spotify_session." >&2
  exit 2
fi
if [[ "$DEPLOY_LEGACY_DEMO_VALUE" != "true" && "$DEPLOY_LEGACY_DEMO_VALUE" != "false" ]]; then
  echo "DEPLOY_LEGACY_DEMO must be true or false." >&2
  exit 2
fi
if [[ "$ENABLE_RESERVED_CONCURRENCY_VALUE" != "true" && "$ENABLE_RESERVED_CONCURRENCY_VALUE" != "false" ]]; then
  echo "ENABLE_RESERVED_CONCURRENCY must be true or false." >&2
  exit 2
fi
if [[ -z "$SAM_ARTIFACT_BUCKET" ]]; then
  echo "SAM_ARTIFACT_BUCKET is required for scoped deployment." >&2
  exit 2
fi
if [[ ! "$CLOUDFORMATION_EXECUTION_ROLE_ARN" =~ ^arn:[^:]+:iam::[0-9]{12}:role/.+ ]]; then
  echo "CLOUDFORMATION_EXECUTION_ROLE_ARN must be a valid IAM role ARN." >&2
  exit 2
fi

if ! aws secretsmanager describe-secret \
  --region "$AWS_REGION_VALUE" \
  --secret-id "$PRODUCT_RUNTIME_SECRET_NAME" >/dev/null; then
  echo "The product runtime secret must exist before deployment." >&2
  exit 2
fi

product_secret="$(aws secretsmanager get-secret-value \
  --region "$AWS_REGION_VALUE" \
  --secret-id "$PRODUCT_RUNTIME_SECRET_NAME" \
  --query SecretString \
  --output text)"
if ! jq -e '
  (.SUPABASE_DB_URL | type == "string" and length > 0)
  and (.SPOTIFY_APP_CLIENT_ID | type == "string" and length > 0)
  and (.SPOTIFY_APP_CLIENT_SECRET | type == "string" and length > 0)
  and (.OBSERVABILITY_HASH_KEY | type == "string" and length >= 32 and length <= 512)
' >/dev/null <<<"$product_secret"; then
  unset product_secret
  echo "The product runtime secret is missing required keys." >&2
  exit 2
fi
supabase_db_url="$(jq -er '.SUPABASE_DB_URL' <<<"$product_secret")"
unset product_secret

preflight_json="$(env \
  AUTH_MODE=api_key \
  RUNTIME_STORE_BACKEND=supabase \
  SUPABASE_DB_URL="$supabase_db_url" \
  uv run python -m music_recommender.deployment_preflight)"
unset supabase_db_url
if ! jq -e '.status == "ready" and .expected_count == .applied_count' \
  >/dev/null <<<"$preflight_json"; then
  echo "Supabase migration preflight failed." >&2
  exit 2
fi
unset preflight_json

legacy_data_bucket="${DATA_BUCKET_NAME:-${MUSIC_RECOMMENDER_BUCKET:-}}"
legacy_catalog_run="${CATALOG_RUN_ID:-${RECOMMENDER_CATALOG_RUN_ID:-}}"
legacy_interaction_run="${INTERACTION_RUN_ID:-${RECOMMENDER_INTERACTION_RUN_ID:-}}"
legacy_data_prefix="${DATA_PREFIX:-}"
legacy_runtime_secret="${RUNTIME_SECRET_NAME:-music-recommender/demo/runtime}"
if [[ "$DEPLOY_LEGACY_DEMO_VALUE" == "true" ]]; then
  for legacy_value in legacy_data_bucket legacy_catalog_run legacy_interaction_run; do
    if [[ -z "${!legacy_value}" ]]; then
      echo "Legacy deployment requires bucket, catalog run, and interaction run values." >&2
      exit 2
    fi
  done
  if ! aws s3api head-bucket --bucket "$legacy_data_bucket" >/dev/null 2>&1; then
    echo "Legacy data bucket is not accessible." >&2
    exit 2
  fi
  readiness_json="$(uv run music-recommender-demo-readiness check-s3-data \
    --bucket "$legacy_data_bucket" \
    --catalog-run-id "$legacy_catalog_run" \
    --profile-run-id "$legacy_interaction_run")"
  if ! jq -e '.catalog.ready == true and .profile.ready == true' \
    >/dev/null <<<"$readiness_json"; then
    echo "Legacy catalog/profile data is not ready." >&2
    exit 2
  fi
fi

bash scripts/prepare_lambda_build.sh
sam validate --lint --template-file infra/template.yaml
sam build --template-file infra/template.yaml
bash scripts/prune_lambda_artifacts.sh

MAX_LAMBDA_UNZIPPED_KB=262144
MAX_PRODUCT_UNZIPPED_KB=131072
for function_name in \
  MusicRecommenderApiFunction \
  MusicRecommenderProfileSyncFunction \
  OutsideTheLoopApiFunction \
  OutsideTheLoopDiscoveryWorkerFunction \
  OutsideTheLoopCleanupFunction; do
  artifact_dir=".aws-sam/build/${function_name}"
  artifact_size_kb="$(du -sk "$artifact_dir" | awk '{print $1}')"
  size_limit="$MAX_LAMBDA_UNZIPPED_KB"
  if [[ "$function_name" == OutsideTheLoop* ]]; then
    size_limit="$MAX_PRODUCT_UNZIPPED_KB"
  fi
  if (( artifact_size_kb >= size_limit )); then
    printf '%s is too large: %s KB (limit: %s KB).\n' \
      "$function_name" "$artifact_size_kb" "$size_limit" >&2
    exit 2
  fi
  printf '%s package size: %s KB.\n' "$function_name" "$artifact_size_kb"
done

parameter_overrides=(
  "StageName=\$default"
  "ProductAuthMode=${PRODUCT_AUTH_MODE_VALUE}"
  "AppBaseUrl=${APP_BASE_URL_VALUE}"
  "ProductRuntimeSecretName=${PRODUCT_RUNTIME_SECRET_NAME}"
  "MusicBrainzContactEmail=${MUSICBRAINZ_CONTACT_EMAIL_VALUE}"
  "SpotifyMarket=${SPOTIFY_MARKET_VALUE}"
  "DeployLegacyDemo=${DEPLOY_LEGACY_DEMO_VALUE}"
  "EnableReservedConcurrency=${ENABLE_RESERVED_CONCURRENCY_VALUE}"
)
if [[ "$DEPLOY_LEGACY_DEMO_VALUE" == "true" ]]; then
  parameter_overrides+=(
    "DataBucketName=${legacy_data_bucket}"
    "CatalogRunId=${legacy_catalog_run}"
    "InteractionRunId=${legacy_interaction_run}"
    "RuntimeSecretName=${legacy_runtime_secret}"
  )
  if [[ -n "$legacy_data_prefix" ]]; then
    parameter_overrides+=("DataPrefix=${legacy_data_prefix}")
  fi
fi

sam deploy \
  --stack-name "$STACK_NAME" \
  --region "$AWS_REGION_VALUE" \
  --template-file .aws-sam/build/template.yaml \
  --capabilities CAPABILITY_IAM \
  --s3-bucket "$SAM_ARTIFACT_BUCKET" \
  --s3-prefix "$STACK_NAME" \
  --role-arn "$CLOUDFORMATION_EXECUTION_ROLE_ARN" \
  --no-confirm-changeset \
  --no-fail-on-empty-changeset \
  --parameter-overrides "${parameter_overrides[@]}"

api_url="$(aws cloudformation describe-stacks \
  --region "$AWS_REGION_VALUE" \
  --stack-name "$STACK_NAME" \
  --query 'Stacks[0].Outputs[?OutputKey==`ProductApiUrl`].OutputValue | [0]' \
  --output text)"
printf 'Product SAM deploy finished for stack %s in %s: %s\n' \
  "$STACK_NAME" "$AWS_REGION_VALUE" "$api_url"
