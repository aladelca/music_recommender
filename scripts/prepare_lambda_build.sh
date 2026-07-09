#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_ROOT="${LAMBDA_BUILD_ROOT:-$ROOT_DIR/.lambda-build}"

if [[ -z "$BUILD_ROOT" || "$BUILD_ROOT" == "/" ]]; then
  echo "Refusing to use an unsafe Lambda build root." >&2
  exit 2
fi

for requirements_file in \
  "$ROOT_DIR/infra/lambda/api-requirements.txt" \
  "$ROOT_DIR/infra/lambda/profile-sync-requirements.txt"; do
  if [[ ! -f "$requirements_file" ]]; then
    printf 'Missing compiled Lambda requirements: %s\n' "$requirements_file" >&2
    exit 2
  fi
done

rm -rf "$BUILD_ROOT"
mkdir -p "$BUILD_ROOT/api" "$BUILD_ROOT/profile-sync"
cp -R "$ROOT_DIR/src" "$BUILD_ROOT/api/src"
cp -R "$ROOT_DIR/src" "$BUILD_ROOT/profile-sync/src"
cp "$ROOT_DIR/infra/lambda/api-requirements.txt" "$BUILD_ROOT/api/requirements.txt"
cp "$ROOT_DIR/infra/lambda/profile-sync-requirements.txt" \
  "$BUILD_ROOT/profile-sync/requirements.txt"

for context_dir in "$BUILD_ROOT/api" "$BUILD_ROOT/profile-sync"; do
  forbidden_data_file="$(find "$context_dir" -type f \
    \( -iname '*.parquet' -o -iname '*.csv' \) -print -quit)"
  if [[ -n "$forbidden_data_file" ]]; then
    printf 'Refusing to package forbidden deployment data file: %s\n' \
      "$forbidden_data_file" >&2
    exit 2
  fi
done

printf 'Prepared isolated Lambda build contexts at %s.\n' "$BUILD_ROOT"
