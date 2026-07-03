#!/usr/bin/env bash
set -euo pipefail

API_URL="${API_URL:-http://127.0.0.1:8000}"
SESSION_ID="${SESSION_ID:?Set SESSION_ID from a recommendation response.}"
TRACK_IDS_JSON="${TRACK_IDS_JSON:?Set TRACK_IDS_JSON to a JSON array of Spotify track IDs.}"

curl -sS -X POST "${API_URL}/playlists" \
  -H 'Content-Type: application/json' \
  -d "{
    \"session_id\": \"${SESSION_ID}\",
    \"name\": \"Music Recommender Demo\",
    \"description\": \"Created by the class demo API\",
    \"track_ids\": ${TRACK_IDS_JSON},
    \"public\": false
  }"
