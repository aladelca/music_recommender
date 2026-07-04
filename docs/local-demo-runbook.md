# Local API Demo Runbook

This runbook reproduces the API-only beta demo locally. It covers the current repo state as of the
session-persistence implementation: recommendation sessions are persisted locally, feedback is local,
and Spotify playlist creation requires a Spotify user refresh token.

## Current Repo Status

- Branch checked before writing this runbook: `main`
- Working tree status before writing this runbook: clean and aligned with `origin/main`
- Existing local catalog run found: `data/local/smoke-reccobeats-parquet`
- Catalog readiness check passed:
  - `silver/tracks`: 41 rows
  - `silver/audio_features`: 29 rows
- `.env` currently has these values present:
  - `SPOTIFY_APP_CLIENT_ID`
  - `SPOTIFY_APP_CLIENT_SECRET`
  - `OPENAI_API_KEY`
- `.env` is missing the Spotify user refresh token needed for profile sync and playlist creation.

## What Can Run Now

With the current local data and `.env`, you can run:

- `GET /health`
- `POST /recommendations`
- `POST /feedback`, after using a valid `session_id` and recommended `track_id`
- Agent CLI recommendations, with or without the OpenAI intent parser

You cannot complete these routes until `SPOTIFY_USER_REFRESH_TOKEN` is added with the required
Spotify scopes:

- `POST /profile/sync`
- `POST /playlists`

Without the refresh token, playlist creation returns:

```json
{"detail":"SPOTIFY_USER_REFRESH_TOKEN is required for this route."}
```

## Prerequisites

- Python 3.12
- `uv`
- `curl`
- `jq`, recommended for extracting `session_id` and track IDs from JSON responses
- Spotify app credentials in `.env`
- Optional: OpenAI API key in `.env` when testing `use_openai_agent=true`
- Optional: Spotify user refresh token in `.env` when testing live profile sync or playlist creation

Install dependencies:

```bash
uv sync
```

## Required `.env` Values

The minimum local recommendation demo needs Spotify app credentials and a catalog run ID:

```bash
SPOTIFY_APP_CLIENT_ID=...
SPOTIFY_APP_CLIENT_SECRET=...
OPENAI_API_KEY=...
RECOMMENDER_DATA_ROOT=data/local
RECOMMENDER_DATA_MODE=local
RECOMMENDER_CATALOG_RUN_ID=smoke-reccobeats-parquet
```

For authenticated API calls, add an API key. If this value is set, every script or `curl` request
except `/health`, `/docs`, `/redoc`, and `/openapi.json` must send `X-API-Key`.

```bash
RECOMMENDER_API_KEY=local-demo-key
```

For live Spotify profile sync and playlist creation, add:

```bash
SPOTIFY_REDIRECT_URI=https://www.google.com/
SPOTIFY_USER_REFRESH_TOKEN=...
SPOTIFY_DEMO_USER_ID=12175364859
SPOTIFY_USER_SCOPES="user-top-read user-library-read playlist-read-private playlist-modify-private playlist-modify-public"
```

Recommended local state paths:

```bash
RECOMMENDER_PROFILE_CACHE_PATH=data/local/api_state/profile.json
RECOMMENDER_SESSION_STORE_PATH=data/local/api_state/sessions.json
RECOMMENDER_PLAYLIST_STORE_PATH=data/local/api_state/playlists.json
RECOMMENDER_FEEDBACK_STORE_PATH=data/local/api_state/feedback.json
```

If you use `RECOMMENDER_API_KEY` from `.env`, export the file before running shell scripts so the
scripts can send the header:

```bash
set -a
source .env
set +a
```

## Validate Local Catalog Data

Run the built-in readiness check:

```bash
uv run music-recommender-demo-readiness check-data \
  --data-root data/local \
  --run-id smoke-reccobeats-parquet
```

Expected result:

```json
{
  "ready": true,
  "root": "data/local",
  "run_id": "smoke-reccobeats-parquet"
}
```

The actual output also includes row counts for each required dataset.

## Start The Local API

If the env vars are already in `.env`, run:

```bash
uv run music-recommender-api --host 127.0.0.1 --port 8000 --reload
```

If you do not want to edit `.env`, provide the demo env vars inline:

```bash
RECOMMENDER_CATALOG_RUN_ID=smoke-reccobeats-parquet \
RECOMMENDER_DATA_ROOT=data/local \
RECOMMENDER_DATA_MODE=local \
RECOMMENDER_PROFILE_CACHE_PATH=data/local/api_state/profile.json \
RECOMMENDER_SESSION_STORE_PATH=data/local/api_state/sessions.json \
RECOMMENDER_PLAYLIST_STORE_PATH=data/local/api_state/playlists.json \
RECOMMENDER_FEEDBACK_STORE_PATH=data/local/api_state/feedback.json \
uv run music-recommender-api --host 127.0.0.1 --port 8000 --reload
```

Use a different port if `8000` is already busy.

## Check Health

In another terminal:

```bash
curl -sS http://127.0.0.1:8000/health | jq
```

Expected fields:

```json
{
  "status": "ok",
  "config": {
    "openai_api_key_present": true,
    "spotify_client_id_present": true,
    "spotify_client_secret_present": true,
    "spotify_user_refresh_token_present": false
  }
}
```

`spotify_user_refresh_token_present` should become `true` after adding
`SPOTIFY_USER_REFRESH_TOKEN`.

## Request Recommendations

Without API key:

```bash
curl -sS -X POST http://127.0.0.1:8000/recommendations \
  -H 'Content-Type: application/json' \
  -d '{
    "prompt": "I just broke up with my girlfriend and I want songs to cheer me up",
    "limit": 10,
    "create_playlist": false
  }' | tee /tmp/music-recommendations.json | jq
```

With API key:

```bash
curl -sS -X POST http://127.0.0.1:8000/recommendations \
  -H "X-API-Key: ${RECOMMENDER_API_KEY}" \
  -H 'Content-Type: application/json' \
  -d '{
    "prompt": "I just broke up with my girlfriend and I want songs to cheer me up",
    "limit": 10,
    "create_playlist": false
  }' | tee /tmp/music-recommendations.json | jq
```

Expected response fields:

- `session_id`
- `intent`
- `recommendations`
- `recommendations[].track.id`
- `recommendations[].track.spotify_url`

Save values for later API calls:

```bash
SESSION_ID="$(jq -r '.session_id' /tmp/music-recommendations.json)"
TRACK_IDS_JSON="$(jq -c '[.recommendations[0:5][].track.id]' /tmp/music-recommendations.json)"
echo "$SESSION_ID"
echo "$TRACK_IDS_JSON"
```

## Record Feedback Locally

Feedback does not need Spotify user OAuth. It does require a valid recommendation session and a
track ID returned by that session.

```bash
TRACK_ID="$(jq -r '.recommendations[0].track.id' /tmp/music-recommendations.json)"

curl -sS -X POST http://127.0.0.1:8000/feedback \
  -H 'Content-Type: application/json' \
  -d "{
    \"session_id\": \"${SESSION_ID}\",
    \"track_id\": \"${TRACK_ID}\",
    \"event_type\": \"like\",
    \"metadata\": {\"source\": \"local-demo\"}
  }" | jq
```

Expected response:

```json
{
  "event_id": "...",
  "status": "recorded"
}
```

Feedback is written to `data/local/api_state/feedback.json`, unless
`RECOMMENDER_FEEDBACK_STORE_PATH` overrides it.

## Enable Spotify User OAuth

Use this section only if `.env` does not yet have `SPOTIFY_USER_REFRESH_TOKEN`.

Official references:

- Spotify Authorization Code Flow: <https://developer.spotify.com/documentation/web-api/tutorials/code-flow>
- Spotify Scopes: <https://developer.spotify.com/documentation/web-api/concepts/scopes>
- Spotify Quota Modes: <https://developer.spotify.com/documentation/web-api/concepts/quota-modes>

Before generating the authorization URL, open the Spotify Developer Dashboard and confirm the app has
this redirect URI registered exactly:

```text
https://www.google.com/
```

For development-mode Spotify apps, the Spotify account approving the app must be allowed in the
app's users management settings. For a production app, use a redirect URI on a domain you control;
this demo uses the URI currently registered in the Spotify app.

Generate the authorization URL:

```bash
uv run music-recommender-demo-readiness auth-url
```

Open the returned `authorization_url`, approve the Spotify app, and copy the `code` query parameter
from the redirect URL. The redirect will look like this:

```text
https://www.google.com/?code=...&state=...
```

Exchange the code:

```bash
uv run music-recommender-demo-readiness exchange-code \
  --code "<spotify-callback-code>" \
  --show-refresh-token
```

Copy the returned refresh token into `.env` as `SPOTIFY_USER_REFRESH_TOKEN`.

Validate the token and scopes:

```bash
uv run music-recommender-demo-readiness refresh-spotify-token
uv run music-recommender-demo-readiness check-live-profile --include-playlists
```

The scope check should return an empty `missing_required_scopes` list.

## Sync Live Spotify Profile

After adding `SPOTIFY_USER_REFRESH_TOKEN`, run:

```bash
bash scripts/demo_sync_profile.sh | jq
```

If `RECOMMENDER_API_KEY` is set, export `.env` first or call the API manually with the
`X-API-Key` header.

Expected result:

- Saved track counts are present
- Top track and artist counts are present
- Playlist counts are present when `include_playlists` is true
- A profile cache is written to `data/local/api_state/profile.json`, unless overridden

## Create A Spotify Playlist

Playlist creation must use the `session_id` from a recommendation response and track IDs from that
same response. The API rejects unknown sessions and non-recommended tracks.

With the helper script:

```bash
SESSION_ID="$SESSION_ID" \
TRACK_IDS_JSON="$TRACK_IDS_JSON" \
bash scripts/demo_create_playlist.sh | jq
```

Manual request without API key:

```bash
curl -sS -X POST http://127.0.0.1:8000/playlists \
  -H 'Content-Type: application/json' \
  -d "{
    \"session_id\": \"${SESSION_ID}\",
    \"name\": \"Music Recommender Demo\",
    \"description\": \"Created by the class demo API\",
    \"track_ids\": ${TRACK_IDS_JSON},
    \"public\": false
  }" | jq
```

Expected response:

```json
{
  "playlist_id": "...",
  "url": "https://open.spotify.com/playlist/...",
  "tracks_added": 5,
  "idempotent_replay": false
}
```

Playlist results are written to `data/local/api_state/playlists.json`, unless
`RECOMMENDER_PLAYLIST_STORE_PATH` overrides it.

## Optional: Use The OpenAI Agent

The recommendation endpoint uses deterministic intent parsing by default. To test the OpenAI Agents
SDK path, keep `OPENAI_API_KEY` in `.env` and send `use_openai_agent: true`:

```bash
curl -sS -X POST http://127.0.0.1:8000/recommendations \
  -H 'Content-Type: application/json' \
  -d '{
    "prompt": "I want upbeat songs that still feel emotionally honest",
    "limit": 10,
    "create_playlist": false,
    "use_openai_agent": true
  }' | jq
```

You can also test the CLI:

```bash
uv run music-recommender-agent recommend \
  --prompt "I want upbeat songs that still feel emotionally honest" \
  --data-root data/local \
  --catalog-run-id smoke-reccobeats-parquet \
  --limit 10 \
  --use-openai-agent
```

## Troubleshooting

- `Set RECOMMENDER_CATALOG_RUN_ID or pass catalog_run_id in the request.`
  - Set `RECOMMENDER_CATALOG_RUN_ID=smoke-reccobeats-parquet` in `.env`, export it in the shell, or
    pass `catalog_run_id` in the recommendation request.
- `SPOTIFY_USER_REFRESH_TOKEN is required for this route.`
  - Create a Spotify user refresh token before calling `/profile/sync` or `/playlists`.
- `Invalid API key.`
  - Export `.env` before running scripts, or unset `RECOMMENDER_API_KEY` for a no-auth local demo.
- Playlist request returns `Track IDs were not recommended for this session`.
  - Reuse only track IDs from the same `/recommendations` response as the `session_id`.
- `jq: command not found`
  - Install `jq`, or copy `session_id` and track IDs manually from the JSON response.

## Clean Local Demo State

Local API state is ignored by git and can be removed when you want a fresh demo:

```bash
rm -f data/local/api_state/profile.json
rm -f data/local/api_state/sessions.json
rm -f data/local/api_state/playlists.json
rm -f data/local/api_state/feedback.json
```

If you used the code defaults before setting explicit state paths, also remove:

```bash
rm -f data/local/api_state/recommender_session_store_path.json
rm -f data/local/api_state/recommender_feedback_store_path.json
```
