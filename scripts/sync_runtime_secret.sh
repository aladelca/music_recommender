#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env}"
AWS_REGION_VALUE="${AWS_REGION_VALUE:-${AWS_REGION:-${AWS_DEFAULT_REGION:-us-east-1}}}"
RUNTIME_SECRET_NAME="${RUNTIME_SECRET_NAME:-music-recommender/product/runtime}"

for required_command in aws jq; do
  if ! command -v "$required_command" >/dev/null 2>&1; then
    printf 'Required command is not installed: %s\n' "$required_command" >&2
    exit 1
  fi
done

if [[ ! -f "$ENV_FILE" ]]; then
  printf 'Environment file does not exist: %s\n' "$ENV_FILE" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

missing_values=()
for required_value in \
  SPOTIFY_APP_CLIENT_ID \
  SPOTIFY_APP_CLIENT_SECRET \
  SUPABASE_DB_URL \
  OBSERVABILITY_HASH_KEY; do
  if [[ -z "${!required_value:-}" ]]; then
    missing_values+=("$required_value")
  fi
done

if (( ${#missing_values[@]} > 0 )); then
  printf 'Missing required runtime secret values: %s\n' "${missing_values[*]}" >&2
  exit 1
fi
if (( ${#OBSERVABILITY_HASH_KEY} < 32 || ${#OBSERVABILITY_HASH_KEY} > 512 )); then
  echo "OBSERVABILITY_HASH_KEY must contain between 32 and 512 characters." >&2
  exit 1
fi

secret_action="created"
if aws secretsmanager describe-secret \
  --region "$AWS_REGION_VALUE" \
  --secret-id "$RUNTIME_SECRET_NAME" >/dev/null 2>&1; then
  secret_action="updated"
fi

secret_json="$(jq -cn \
  --arg spotify_client_id "$SPOTIFY_APP_CLIENT_ID" \
  --arg spotify_client_secret "$SPOTIFY_APP_CLIENT_SECRET" \
  --arg supabase_db_url "$SUPABASE_DB_URL" \
  --arg observability_hash_key "$OBSERVABILITY_HASH_KEY" \
  '{
    SPOTIFY_APP_CLIENT_ID: $spotify_client_id,
    SPOTIFY_APP_CLIENT_SECRET: $spotify_client_secret,
    SUPABASE_DB_URL: $supabase_db_url,
    OBSERVABILITY_HASH_KEY: $observability_hash_key
  }')"

if [[ "$secret_action" == "updated" ]]; then
  printf '%s' "$secret_json" | aws secretsmanager put-secret-value \
    --region "$AWS_REGION_VALUE" \
    --secret-id "$RUNTIME_SECRET_NAME" \
    --secret-string file:///dev/stdin >/dev/null
else
  printf '%s' "$secret_json" | aws secretsmanager create-secret \
    --region "$AWS_REGION_VALUE" \
    --name "$RUNTIME_SECRET_NAME" \
    --description "Runtime credentials for the Outside the Loop product API" \
    --secret-string file:///dev/stdin >/dev/null
fi

printf 'Runtime secret %s in %s (%s).\n' \
  "$RUNTIME_SECRET_NAME" \
  "$AWS_REGION_VALUE" \
  "$secret_action"
