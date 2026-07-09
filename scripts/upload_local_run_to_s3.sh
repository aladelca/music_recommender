#!/usr/bin/env bash
set -euo pipefail

RUN_ID="${1:-${RUN_ID:-}}"
if [[ -z "${RUN_ID}" ]]; then
  echo "Usage: RUN_ID=<run-id> MUSIC_RECOMMENDER_BUCKET=<bucket> $0" >&2
  echo "   or: MUSIC_RECOMMENDER_BUCKET=<bucket> $0 <run-id>" >&2
  exit 2
fi

BUCKET="${MUSIC_RECOMMENDER_BUCKET:-}"
if [[ -z "${BUCKET}" ]]; then
  echo "MUSIC_RECOMMENDER_BUCKET is required." >&2
  exit 2
fi

LOCAL_ROOT="${LOCAL_DATA_ROOT:-data/local}"
SOURCE="${LOCAL_ROOT%/}/${RUN_ID}"
if [[ ! -d "${SOURCE}" ]]; then
  echo "Local run directory does not exist: ${SOURCE}" >&2
  exit 2
fi

aws s3 sync "${SOURCE}/" "s3://${BUCKET}/" \
  --exclude "api_state/*" \
  --exclude "*.tmp"

echo "Uploaded ${SOURCE}/ to s3://${BUCKET}/"
