#!/usr/bin/env bash
set -euo pipefail

API_URL="${API_URL:-http://127.0.0.1:8000}"
CURL_ARGS=(-sS -X POST "${API_URL}/recommendations")
if [[ -n "${RECOMMENDER_API_KEY:-}" ]]; then
  CURL_ARGS+=(-H "X-API-Key: ${RECOMMENDER_API_KEY}")
fi
CURL_ARGS+=(
  -H 'Content-Type: application/json'
  -d '{
    "prompt": "I just broke up with my girlfriend and I want songs to cheer me up",
    "limit": 10,
    "create_playlist": false
  }'
)

curl "${CURL_ARGS[@]}"
