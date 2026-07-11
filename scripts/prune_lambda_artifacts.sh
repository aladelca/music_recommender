#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARTIFACT_ROOT="${LAMBDA_ARTIFACT_ROOT:-$ROOT_DIR/.aws-sam/build}"
API_ARTIFACT="$ARTIFACT_ROOT/MusicRecommenderApiFunction"
PROFILE_SYNC_ARTIFACT="$ARTIFACT_ROOT/MusicRecommenderProfileSyncFunction"
PRODUCT_API_ARTIFACT="$ARTIFACT_ROOT/OutsideTheLoopApiFunction"
DISCOVERY_WORKER_ARTIFACT="$ARTIFACT_ROOT/OutsideTheLoopDiscoveryWorkerFunction"
CLEANUP_ARTIFACT="$ARTIFACT_ROOT/OutsideTheLoopCleanupFunction"

artifact_dirs=(
  "$API_ARTIFACT"
  "$PROFILE_SYNC_ARTIFACT"
  "$PRODUCT_API_ARTIFACT"
  "$DISCOVERY_WORKER_ARTIFACT"
  "$CLEANUP_ARTIFACT"
)

for artifact_dir in "${artifact_dirs[@]}"; do
  if [[ ! -d "$artifact_dir" ]]; then
    printf 'Lambda artifact directory does not exist: %s\n' "$artifact_dir" >&2
    exit 2
  fi
done

# PyArrow distributes test fixtures that are not needed to read production S3 datasets.
rm -rf "$API_ARTIFACT/pyarrow/tests"

for artifact_dir in "${artifact_dirs[@]}"; do
  forbidden_data_file="$(find "$artifact_dir" -type f \
    \( -iname '*.parquet' -o -iname '*.csv' -o -name '.env' \) -print -quit)"
  if [[ -n "$forbidden_data_file" ]]; then
    printf 'Lambda artifact contains a forbidden Parquet/CSV file: %s\n' \
      "$forbidden_data_file" >&2
    exit 2
  fi
done

echo "Lambda artifacts contain no Parquet or CSV files."
