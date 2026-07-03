#!/usr/bin/env bash
set -euo pipefail

API_URL="${API_URL:-http://127.0.0.1:8000}"

curl -sS -X POST "${API_URL}/recommendations" \
  -H 'Content-Type: application/json' \
  -d '{
    "prompt": "I just broke up with my girlfriend and I want songs to cheer me up",
    "limit": 10,
    "create_playlist": false
  }'
