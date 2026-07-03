#!/usr/bin/env bash
set -euo pipefail

API_URL="${API_URL:-http://127.0.0.1:8000}"

curl -sS -X POST "${API_URL}/profile/sync" \
  -H 'Content-Type: application/json' \
  -d '{
    "top_limit": 20,
    "saved_limit": 20
  }'
