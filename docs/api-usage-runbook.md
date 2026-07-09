# Deployed API Usage Runbook

This runbook covers the secured, single-user API deployed by the
`music-recommender-demo` CloudFormation stack in `us-east-1`. The current endpoint is
`https://4bds6ddj39.execute-api.us-east-1.amazonaws.com/`.

The interactive OpenAPI UI is public at `/docs`. The profile, recommendation, feedback, and
playlist routes require `X-API-Key`. The API key authenticates the caller to the one configured
Spotify account; it is not a multi-user Spotify login flow.

## Prerequisites

- AWS CLI access that can read the stack outputs and runtime secret
- `curl` and `jq`
- Permission to use the recommender API key
- Spotify credentials and refresh token already provisioned in the deployed runtime secret

Do not print, log, commit, or place the API key directly in a curl command. Command arguments can be
visible to other local processes.

## Prepare A Secure Shell Session

Resolve the deployed URL and write the API key to a mode-restricted curl header file. The secret is
removed automatically when the shell exits.

```bash
export AWS_REGION_VALUE=us-east-1
export STACK_NAME=music-recommender-demo
export RUNTIME_SECRET_NAME=music-recommender/demo/runtime

export API_URL="$(aws cloudformation describe-stacks \
  --region "$AWS_REGION_VALUE" \
  --stack-name "$STACK_NAME" \
  --query 'Stacks[0].Outputs[?OutputKey==`ApiUrl`].OutputValue | [0]' \
  --output text)"
export API_URL="${API_URL%/}"

umask 077
export API_WORK_DIR="$(mktemp -d)"
export AUTH_HEADER_FILE="$API_WORK_DIR/auth-header"
trap 'rm -rf "$API_WORK_DIR"' EXIT

runtime_secret="$(aws secretsmanager get-secret-value \
  --region "$AWS_REGION_VALUE" \
  --secret-id "$RUNTIME_SECRET_NAME" \
  --query SecretString \
  --output text)"
api_key="$(printf '%s' "$runtime_secret" | jq -er \
  '.RECOMMENDER_API_KEY | select(type == "string" and length >= 32)')"
printf 'X-API-Key: %s\n' "$api_key" > "$AUTH_HEADER_FILE"
unset runtime_secret api_key
```

For a client outside the deployment team, deliver the key through an approved secret-management
channel. Do not grant that client AWS Secrets Manager access merely to call this API.

## Check Health And Authentication

`GET /health`, `/docs`, `/redoc`, and `/openapi.json` are public. Health reports configuration
presence only, never credential values.

```bash
curl -fsS "$API_URL/health" | jq '{status, version, config}'
```

A protected request without the header must return HTTP `401`:

```bash
curl -sS \
  --output "$API_WORK_DIR/unauthorized.json" \
  --write-out 'HTTP %{http_code}\n' \
  "$API_URL/profile"
jq . "$API_WORK_DIR/unauthorized.json"
```

The expected body is `{"detail":"Invalid API key."}`.

## Sync The Spotify Profile

`POST /profile/sync` refreshes the configured Spotify user's profile and writes it to DynamoDB. It
can read saved tracks, top tracks and artists, selected or current-user playlists, and optionally
recently played tracks. This route calls Spotify synchronously and can take longer than a
recommendation.

```bash
cat > "$API_WORK_DIR/profile-sync-request.json" <<'JSON'
{
  "top_limit": 20,
  "saved_limit": 20,
  "top_time_ranges": ["short_term", "medium_term", "long_term"],
  "include_playlists": true,
  "playlist_limit": 10,
  "playlist_track_limit": 50,
  "playlist_ids": [],
  "include_recently_played": false,
  "recently_played_limit": 20,
  "market": null
}
JSON

curl -fsS \
  -H "@$AUTH_HEADER_FILE" \
  -H 'Content-Type: application/json' \
  --data @"$API_WORK_DIR/profile-sync-request.json" \
  --output "$API_WORK_DIR/profile-sync.json" \
  "$API_URL/profile/sync"

jq '{
  source,
  synced_at,
  source_counts,
  time_ranges,
  playlist_sources,
  missing_optional_scopes
}' "$API_WORK_DIR/profile-sync.json"
```

Use `playlist_ids` to restrict playlist ingestion to explicitly selected Spotify playlist IDs. A
missing optional scope is reported in `missing_optional_scopes`; accessible profile sources are
still cached.

## Inspect Cached Profile Status

Use the status route to confirm freshness without printing the user's full taste profile:

```bash
curl -fsS \
  -H "@$AUTH_HEADER_FILE" \
  --output "$API_WORK_DIR/profile.json" \
  "$API_URL/profile"

jq '{
  present,
  source,
  synced_at,
  source_counts,
  time_ranges,
  missing_optional_scopes,
  liked_track_count: (.profile.liked_track_ids | length),
  known_track_count: (.profile.known_track_ids | length),
  liked_artist_count: (.profile.liked_artist_names | length)
}' "$API_WORK_DIR/profile.json"
```

Before the first successful sync, the route returns `present: false`, `profile: null`, and
`synced_at: null`.

## Request Recommendations

The default deterministic path parses the prompt with local rules and ranks only catalog-backed or
synced Spotify-profile tracks.

```bash
cat > "$API_WORK_DIR/recommendation-request.json" <<'JSON'
{
  "prompt": "Give me upbeat, clean songs that still feel emotionally honest",
  "limit": 5,
  "create_playlist": false,
  "playlist_name": null,
  "playlist_public": true,
  "use_openai_agent": false,
  "liked_artist_names": [],
  "liked_track_ids": [],
  "known_track_ids": [],
  "blocked_artist_names": []
}
JSON

curl -fsS \
  -H "@$AUTH_HEADER_FILE" \
  -H 'Content-Type: application/json' \
  --data @"$API_WORK_DIR/recommendation-request.json" \
  --output "$API_WORK_DIR/recommendation.json" \
  "$API_URL/recommendations"

jq '{
  session_id,
  intent,
  recommendations: [
    .recommendations[] | {
      track_id: .track.id,
      name: .track.name,
      artists: .track.artist_names,
      spotify_url: .track.spotify_url,
      score: .score,
      explanation: .explanation
    }
  ],
  playlist_candidate,
  playlist_result
}' "$API_WORK_DIR/recommendation.json"
```

Set `use_openai_agent` to `true` to use the configured OpenAI model for structured intent parsing
and orchestration. The final IDs are still constrained to tracks returned by the deterministic
catalog-ranking tool. An OpenAI outage affects only requests that enable this option.

Request-level `liked_*`, `known_track_ids`, and `blocked_artist_names` values augment the cached
profile for that request. `catalog_run_id`, `interaction_run_id`, and `demo_user_id` are operational
overrides; normal callers should rely on the deployment defaults.

Setting `create_playlist: true` persists the recommendation session and immediately creates the
Spotify playlist from all returned candidate tracks. Add `playlist_name` to replace the generated
`Music Recommender - <intent>` name. `playlist_public` defaults to `true`:

```json
{
  "prompt": "Give me upbeat songs that still feel emotionally honest",
  "limit": 5,
  "create_playlist": true,
  "playlist_name": "Adrian's Upbeat Mix",
  "playlist_public": true,
  "use_openai_agent": false
}
```

`playlist_name` must be non-empty when supplied and has no effect when `create_playlist` is false.
The response includes `playlist_result` with the Spotify playlist ID, URL, tracks added, snapshot
ID, idempotency state, and partial failures. Set `playlist_public` to `false` to request a private
playlist.

## Record Feedback

Feedback must reference a session and track returned by the recommendation response. Supported
event types are `like`, `dislike`, `hide_artist`, `save`, `skip`, and `refine`.

```bash
session_id="$(jq -er '.session_id' "$API_WORK_DIR/recommendation.json")"
track_id="$(jq -er '.recommendations[0].track.id' "$API_WORK_DIR/recommendation.json")"

jq -n \
  --arg session_id "$session_id" \
  --arg track_id "$track_id" \
  '{
    session_id: $session_id,
    track_id: $track_id,
    event_type: "like",
    metadata: {source: "manual-api-runbook"}
  }' > "$API_WORK_DIR/feedback-request.json"

curl -fsS \
  -H "@$AUTH_HEADER_FILE" \
  -H 'Content-Type: application/json' \
  --data @"$API_WORK_DIR/feedback-request.json" \
  "$API_URL/feedback" | jq .
```

The response contains `event_id` and `status: "recorded"`. Feedback is persisted for analysis but
is not yet folded back into profile weights or ranking.

## Create Or Retry A Spotify Playlist Explicitly

Use `POST /playlists` when `create_playlist` was false and you want to review or select a subset of
tracks first. It can also safely replay a session that already created a playlist automatically.
Track IDs must be a non-empty subset from the same recommendation session.

```bash
session_id="$(jq -er '.session_id' "$API_WORK_DIR/recommendation.json")"

jq -n \
  --arg session_id "$session_id" \
  --arg name "Music Recommender - Runbook Test" \
  --argjson track_ids "$(jq -c '[.recommendations[].track.id] | .[:3]' \
    "$API_WORK_DIR/recommendation.json")" \
  '{
    session_id: $session_id,
    name: $name,
    description: "Created after reviewing API recommendations",
    track_ids: $track_ids,
    public: false
  }' > "$API_WORK_DIR/playlist-request.json"

curl -fsS \
  -H "@$AUTH_HEADER_FILE" \
  -H 'Content-Type: application/json' \
  --data @"$API_WORK_DIR/playlist-request.json" \
  --output "$API_WORK_DIR/playlist.json" \
  "$API_URL/playlists"
jq . "$API_WORK_DIR/playlist.json"
```

The response includes `playlist_id`, `url`, `tracks_added`, `snapshot_id`, `partial_failures`, and
`idempotent_replay`. The session ID is the idempotency key: replaying the request returns the stored
result with `idempotent_replay: true` instead of creating another playlist.

## Request Limits And Errors

| Condition | Response |
| --- | --- |
| Missing or invalid `X-API-Key` | `401` |
| Invalid session/track relationship or domain input | `400` |
| Unknown recommendation session | `404` |
| Invalid JSON schema, field type, or range | `422` |
| Missing runtime configuration | `503` |
| Unhandled dependency or application failure | `500` |

`limit` accepts 1 through 50. Profile source limits and allowed values are documented by the live
OpenAPI schema at `$API_URL/docs`.

For a failed call, capture the status and body without exposing request headers:

```bash
curl -sS \
  -H "@$AUTH_HEADER_FILE" \
  --output "$API_WORK_DIR/error.json" \
  --write-out 'HTTP %{http_code}\n' \
  "$API_URL/profile"
jq . "$API_WORK_DIR/error.json"
```

Use [operational-aws-runbook.md](operational-aws-runbook.md) to inspect Lambda and API Gateway logs
or run the complete deployed smoke suite.
