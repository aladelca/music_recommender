#!/usr/bin/env bash
set -euo pipefail

API_URL="${API_URL:-http://127.0.0.1:8000}"
CURL_ARGS=(-sS -X POST "${API_URL}/profile/sync")
if [[ -n "${RECOMMENDER_API_KEY:-}" ]]; then
  CURL_ARGS+=(-H "X-API-Key: ${RECOMMENDER_API_KEY}")
fi
CURL_ARGS+=(
  -H 'Content-Type: application/json'
  -d '{
    "top_time_ranges": ["short_term", "medium_term", "long_term"],
    "top_limit": 20,
    "saved_limit": 50,
    "include_playlists": true,
    "playlist_limit": 10,
    "playlist_track_limit": 100,
    "include_recently_played": false
  }'
)

curl "${CURL_ARGS[@]}"
