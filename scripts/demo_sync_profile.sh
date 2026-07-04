#!/usr/bin/env bash
set -euo pipefail

API_URL="${API_URL:-http://127.0.0.1:8000}"
API_KEY_ARGS=()
if [[ -n "${RECOMMENDER_API_KEY:-}" ]]; then
  API_KEY_ARGS=(-H "X-API-Key: ${RECOMMENDER_API_KEY}")
fi

curl -sS -X POST "${API_URL}/profile/sync" \
  "${API_KEY_ARGS[@]}" \
  -H 'Content-Type: application/json' \
  -d '{
    "top_time_ranges": ["short_term", "medium_term", "long_term"],
    "top_limit": 20,
    "saved_limit": 50,
    "include_playlists": true,
    "playlist_limit": 10,
    "playlist_track_limit": 100,
    "include_recently_played": false
  }'
