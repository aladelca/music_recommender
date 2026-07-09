#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env}"
AWS_REGION_VALUE="${AWS_REGION_VALUE:-${AWS_REGION:-${AWS_DEFAULT_REGION:-us-east-1}}}"
RUNTIME_SECRET_NAME="${RUNTIME_SECRET_NAME:-music-recommender/demo/runtime}"

for required_command in aws jq openssl; do
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
  OPENAI_API_KEY \
  SPOTIFY_APP_CLIENT_ID \
  SPOTIFY_APP_CLIENT_SECRET \
  SPOTIFY_USER_REFRESH_TOKEN; do
  if [[ -z "${!required_value:-}" ]]; then
    missing_values+=("$required_value")
  fi
done

if (( ${#missing_values[@]} > 0 )); then
  printf 'Missing required runtime secret values: %s\n' "${missing_values[*]}" >&2
  exit 1
fi

api_key="${RECOMMENDER_API_KEY:-}"
secret_action="created"
if aws secretsmanager describe-secret \
  --region "$AWS_REGION_VALUE" \
  --secret-id "$RUNTIME_SECRET_NAME" >/dev/null 2>&1; then
  secret_action="updated"
  existing_secret="$(aws secretsmanager get-secret-value \
    --region "$AWS_REGION_VALUE" \
    --secret-id "$RUNTIME_SECRET_NAME" \
    --query SecretString \
    --output text)"
  existing_api_key="$(printf '%s' "$existing_secret" | jq -r '.RECOMMENDER_API_KEY // empty')"
  if [[ -n "$existing_api_key" ]]; then
    api_key="$existing_api_key"
  fi
fi

if (( ${#api_key} < 32 )); then
  api_key="$(openssl rand -hex 32)"
fi

secret_json="$(jq -cn \
  --arg openai_api_key "$OPENAI_API_KEY" \
  --arg recommender_api_key "$api_key" \
  --arg spotify_client_id "$SPOTIFY_APP_CLIENT_ID" \
  --arg spotify_client_secret "$SPOTIFY_APP_CLIENT_SECRET" \
  --arg spotify_refresh_token "$SPOTIFY_USER_REFRESH_TOKEN" \
  '{
    OPENAI_API_KEY: $openai_api_key,
    RECOMMENDER_API_KEY: $recommender_api_key,
    SPOTIFY_APP_CLIENT_ID: $spotify_client_id,
    SPOTIFY_APP_CLIENT_SECRET: $spotify_client_secret,
    SPOTIFY_USER_REFRESH_TOKEN: $spotify_refresh_token
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
    --description "Runtime credentials for the single-user music recommender API" \
    --secret-string file:///dev/stdin >/dev/null
fi

printf 'Runtime secret %s in %s (%s).\n' \
  "$RUNTIME_SECRET_NAME" \
  "$AWS_REGION_VALUE" \
  "$secret_action"
