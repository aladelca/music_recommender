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
    "top_limit": 20,
    "saved_limit": 20
  }'
