#!/usr/bin/env bash
set -euo pipefail

STACK_NAME="${STACK_NAME:-outside-the-loop-beta}"
AWS_REGION_VALUE="${AWS_REGION_VALUE:-${AWS_REGION:-${AWS_DEFAULT_REGION:-us-east-1}}}"

for required_command in aws curl jq mktemp awk; do
  if ! command -v "$required_command" >/dev/null 2>&1; then
    printf 'Required command is not installed: %s\n' "$required_command" >&2
    exit 2
  fi
done

stack_outputs="$(aws cloudformation describe-stacks \
  --region "$AWS_REGION_VALUE" \
  --stack-name "$STACK_NAME" \
  --query 'Stacks[0].Outputs' \
  --output json)"
api_url="$(jq -er '.[] | select(.OutputKey == "ProductApiUrl") | .OutputValue' \
  <<<"$stack_outputs")"
api_url="${api_url%/}"
dlq_url="$(jq -er '.[] | select(.OutputKey == "DiscoveryDlqUrl") | .OutputValue' \
  <<<"$stack_outputs")"

umask 077
tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

request_json() {
  local method="$1"
  local path="$2"
  local output_file="$3"
  curl -sS \
    --request "$method" \
    --output "$output_file" \
    --write-out '%{http_code}' \
    "${api_url}${path}"
}

assert_status() {
  local expected="$1"
  local actual="$2"
  local label="$3"
  if [[ "$actual" != "$expected" ]]; then
    printf '%s returned HTTP %s; expected %s.\n' "$label" "$actual" "$expected" >&2
    exit 1
  fi
}

health_file="$tmp_dir/health.json"
status="$(request_json GET /health "$health_file")"
assert_status "200" "$status" "product health"
jq -e '.status == "ok" and (.version | type == "string")' "$health_file" >/dev/null

ready_file="$tmp_dir/ready.json"
status="$(request_json GET /ready "$ready_file")"
assert_status "200" "$status" "product readiness"
jq -e '.status == "ready"' "$ready_file" >/dev/null

auth_file="$tmp_dir/auth.json"
status="$(request_json GET /auth/me "$auth_file")"
assert_status "401" "$status" "unauthenticated current user"
jq -e '.code == "authentication_required"' "$auth_file" >/dev/null

seeds_file="$tmp_dir/seeds.json"
status="$(request_json GET /me/seeds "$seeds_file")"
assert_status "401" "$status" "unauthenticated seeds"

legacy_file="$tmp_dir/legacy.json"
status="$(request_json POST /recommendations "$legacy_file")"
assert_status "404" "$status" "disabled legacy recommendation route"

oauth_headers="$tmp_dir/oauth-headers"
oauth_body="$tmp_dir/oauth-body"
status="$(curl -sS \
  --request GET \
  --dump-header "$oauth_headers" \
  --output "$oauth_body" \
  --write-out '%{http_code}' \
  "${api_url}/auth/spotify/start?return_to=%2Fdiscover")"
assert_status "302" "$status" "Spotify OAuth start"
oauth_location="$(awk 'BEGIN { IGNORECASE=1 } /^location:/ { sub(/^[^:]+:[[:space:]]*/, ""); sub(/\r$/, ""); print; exit }' "$oauth_headers")"
if [[ "$oauth_location" != https://accounts.spotify.com/authorize* ]]; then
  echo "Spotify OAuth start returned an unexpected location." >&2
  exit 1
fi
unset oauth_location

dlq_count="$(aws sqs get-queue-attributes \
  --region "$AWS_REGION_VALUE" \
  --queue-url "$dlq_url" \
  --attribute-names ApproximateNumberOfMessages \
  --query 'Attributes.ApproximateNumberOfMessages' \
  --output text)"
if [[ "$dlq_count" != "0" ]]; then
  echo "Discovery dead-letter queue is not empty." >&2
  exit 1
fi

jq -n \
  --arg api_url "$api_url" \
  --argjson dlq_messages "$dlq_count" \
  '{status: "ready", api_url: $api_url, oauth_start: "ok", legacy_routes: "disabled", discovery_dlq_messages: $dlq_messages}'
