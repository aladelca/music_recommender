#!/usr/bin/env bash
set -euo pipefail

STACK_NAME="${STACK_NAME:-music-recommender-demo}"
AWS_REGION_VALUE="${AWS_REGION_VALUE:-${AWS_REGION:-${AWS_DEFAULT_REGION:-us-east-1}}}"
RUNTIME_SECRET_NAME="${RUNTIME_SECRET_NAME:-music-recommender/demo/runtime}"
SMOKE_USE_OPENAI_AGENT="${SMOKE_USE_OPENAI_AGENT:-true}"

for required_command in aws curl jq mktemp; do
  if ! command -v "$required_command" >/dev/null 2>&1; then
    printf 'Required command is not installed: %s\n' "$required_command" >&2
    exit 2
  fi
done

if [[ "$SMOKE_USE_OPENAI_AGENT" != "true" && "$SMOKE_USE_OPENAI_AGENT" != "false" ]]; then
  echo "SMOKE_USE_OPENAI_AGENT must be true or false." >&2
  exit 2
fi

stack_outputs="$(aws cloudformation describe-stacks \
  --region "$AWS_REGION_VALUE" \
  --stack-name "$STACK_NAME" \
  --query 'Stacks[0].Outputs' \
  --output json)"
api_url="$(printf '%s' "$stack_outputs" | jq -er \
  '.[] | select(.OutputKey == "ApiUrl") | .OutputValue')"
api_url="${api_url%/}"

runtime_secret="$(aws secretsmanager get-secret-value \
  --region "$AWS_REGION_VALUE" \
  --secret-id "$RUNTIME_SECRET_NAME" \
  --query SecretString \
  --output text)"
api_key="$(printf '%s' "$runtime_secret" | jq -er \
  '.RECOMMENDER_API_KEY | select(type == "string" and length >= 32)')"
unset runtime_secret

umask 077
tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT
auth_header_file="$tmp_dir/auth-header"
printf 'X-API-Key: %s\n' "$api_key" > "$auth_header_file"
unset api_key

request_json() {
  local method="$1"
  local path="$2"
  local auth_required="$3"
  local body="$4"
  local output_file="$5"
  local -a curl_args=(
    -sS
    --request "$method"
    --output "$output_file"
    --write-out '%{http_code}'
  )
  if [[ "$auth_required" == "true" ]]; then
    curl_args+=(-H "@$auth_header_file")
  fi
  if [[ -n "$body" ]]; then
    curl_args+=(-H 'Content-Type: application/json' --data "$body")
  fi
  curl "${curl_args[@]}" "${api_url}${path}"
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
status="$(request_json GET /health false '' "$health_file")"
assert_status "200" "$status" "health"
jq -e '
  .status == "ok" and
  .config.api_key_required == true and
  .config.recommender_data_mode == "s3" and
  .config.runtime_store_backend == "dynamodb" and
  .config.dynamodb_users_table_present == true and
  .config.dynamodb_sessions_table_present == true and
  .config.dynamodb_feedback_table_present == true and
  .config.dynamodb_playlists_table_present == true
' "$health_file" >/dev/null

unauthorized_file="$tmp_dir/unauthorized.json"
status="$(request_json GET /profile false '' "$unauthorized_file")"
assert_status "401" "$status" "unauthenticated profile"

profile_sync_body='{
  "top_limit": 20,
  "saved_limit": 20,
  "top_time_ranges": ["short_term", "medium_term", "long_term"],
  "include_playlists": true,
  "playlist_limit": 10,
  "playlist_track_limit": 50,
  "include_recently_played": false
}'
profile_sync_file="$tmp_dir/profile-sync.json"
status="$(request_json POST /profile/sync true "$profile_sync_body" "$profile_sync_file")"
assert_status "200" "$status" "profile sync"
jq -e '.synced_at and (.source_counts | type == "object")' "$profile_sync_file" >/dev/null

profile_file="$tmp_dir/profile.json"
status="$(request_json GET /profile true '' "$profile_file")"
assert_status "200" "$status" "profile status"
jq -e '.present == true and .synced_at' "$profile_file" >/dev/null

recommendation_body="$(jq -cn \
  --argjson use_openai_agent "$SMOKE_USE_OPENAI_AGENT" \
  '{
    prompt: "Give me upbeat songs that still feel emotionally honest",
    limit: 5,
    create_playlist: false,
    use_openai_agent: $use_openai_agent
  }')"
recommendation_file="$tmp_dir/recommendation.json"
status="$(request_json POST /recommendations true "$recommendation_body" "$recommendation_file")"
assert_status "200" "$status" "recommendation"
jq -e '.session_id and (.recommendations | length > 0)' "$recommendation_file" >/dev/null
session_id="$(jq -er '.session_id' "$recommendation_file")"
first_track_id="$(jq -er '.recommendations[0].track.id' "$recommendation_file")"
track_ids_json="$(jq -c '[.recommendations[].track.id] | .[:3]' "$recommendation_file")"

feedback_body="$(jq -cn \
  --arg session_id "$session_id" \
  --arg track_id "$first_track_id" \
  '{session_id: $session_id, track_id: $track_id, event_type: "like", metadata: {source: "aws-smoke"}}')"
feedback_file="$tmp_dir/feedback.json"
status="$(request_json POST /feedback true "$feedback_body" "$feedback_file")"
assert_status "200" "$status" "feedback"
jq -e '.status == "recorded" and .event_id' "$feedback_file" >/dev/null

playlist_name="Music Recommender AWS Smoke $(date -u +%Y%m%d-%H%M%S)"
playlist_body="$(jq -cn \
  --arg session_id "$session_id" \
  --arg name "$playlist_name" \
  --argjson track_ids "$track_ids_json" \
  '{
    session_id: $session_id,
    name: $name,
    description: "Private playlist created by the AWS deployment smoke test",
    track_ids: $track_ids,
    public: false
  }')"
playlist_file="$tmp_dir/playlist.json"
status="$(request_json POST /playlists true "$playlist_body" "$playlist_file")"
assert_status "200" "$status" "playlist creation"
jq -e 'select(.idempotent_replay == false) | .playlist_id' "$playlist_file" >/dev/null

playlist_replay_file="$tmp_dir/playlist-replay.json"
status="$(request_json POST /playlists true "$playlist_body" "$playlist_replay_file")"
assert_status "200" "$status" "playlist idempotent replay"
jq -e 'select(.idempotent_replay == true) | .playlist_id' "$playlist_replay_file" >/dev/null
playlist_id="$(jq -er '.playlist_id' "$playlist_file")"

jq -n \
  --arg api_url "$api_url" \
  --arg session_id "$session_id" \
  --arg playlist_id "$playlist_id" \
  --argjson recommendation_count "$(jq '.recommendations | length' "$recommendation_file")" \
  --argjson profile_source_counts "$(jq '.source_counts' "$profile_sync_file")" \
  '{
    status: "ready",
    api_url: $api_url,
    session_id: $session_id,
    recommendation_count: $recommendation_count,
    playlist_id: $playlist_id,
    playlist_idempotency_verified: true,
    profile_source_counts: $profile_source_counts
  }'
