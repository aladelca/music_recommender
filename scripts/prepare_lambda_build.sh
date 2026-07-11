#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_ROOT="${LAMBDA_BUILD_ROOT:-$ROOT_DIR/.lambda-build}"

if [[ -z "$BUILD_ROOT" || "$BUILD_ROOT" == "/" ]]; then
  echo "Refusing to use an unsafe Lambda build root." >&2
  exit 2
fi

contexts=(api profile-sync product-api discovery-worker cleanup)
requirements=(
  api-requirements.txt
  profile-sync-requirements.txt
  product-api-requirements.txt
  discovery-worker-requirements.txt
  cleanup-requirements.txt
)

for requirements_file in "${requirements[@]}"; do
  requirements_file="$ROOT_DIR/infra/lambda/$requirements_file"
  if [[ ! -f "$requirements_file" ]]; then
    printf 'Missing compiled Lambda requirements: %s\n' "$requirements_file" >&2
    exit 2
  fi
done

rm -rf "$BUILD_ROOT"
for index in "${!contexts[@]}"; do
  context_dir="$BUILD_ROOT/${contexts[$index]}"
  mkdir -p "$context_dir"
  cp -R "$ROOT_DIR/src" "$context_dir/src"
  cp "$ROOT_DIR/infra/lambda/${requirements[$index]}" "$context_dir/requirements.txt"
done

for context_name in "${contexts[@]}"; do
  context_dir="$BUILD_ROOT/$context_name"
  forbidden_data_file="$(find "$context_dir" -type f \
    \( -iname '*.parquet' -o -iname '*.csv' -o -name '.env' \) -print -quit)"
  if [[ -n "$forbidden_data_file" ]]; then
    printf 'Refusing to package forbidden deployment data file: %s\n' \
      "$forbidden_data_file" >&2
    exit 2
  fi
done

printf 'Prepared isolated Lambda build contexts at %s.\n' "$BUILD_ROOT"
