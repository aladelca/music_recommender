#!/usr/bin/env bash
set -euo pipefail

VERCEL_URL="${1:-}"
if [[ ! "$VERCEL_URL" =~ ^https://[A-Za-z0-9.-]+$ ]]; then
  echo "Usage: verify_vercel_deployment.sh https://your-project.vercel.app" >&2
  exit 2
fi

for required_command in curl mktemp; do
  if ! command -v "$required_command" >/dev/null 2>&1; then
    printf 'Required command is not installed: %s\n' "$required_command" >&2
    exit 2
  fi
done

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

root_headers="$tmp_dir/root-headers"
root_body="$tmp_dir/root.html"
root_status="$(curl -sS --dump-header "$root_headers" --output "$root_body" --write-out '%{http_code}' "$VERCEL_URL/")"
if [[ "$root_status" != "200" ]] || ! grep -q '<div id="root"></div>' "$root_body"; then
  echo "Vercel root did not serve the application shell." >&2
  exit 1
fi

deep_body="$tmp_dir/deep.html"
deep_status="$(curl -sS --output "$deep_body" --write-out '%{http_code}' "$VERCEL_URL/history")"
if [[ "$deep_status" != "200" ]] || ! grep -q '<div id="root"></div>' "$deep_body"; then
  echo "Vercel SPA fallback failed for a deep link." >&2
  exit 1
fi

api_headers="$tmp_dir/api-headers"
api_body="$tmp_dir/api.json"
api_status="$(curl -sS --dump-header "$api_headers" --output "$api_body" --write-out '%{http_code}' "$VERCEL_URL/api/health")"
if [[ "$api_status" != "200" ]] || ! grep -Eq '"status"[[:space:]]*:[[:space:]]*"ok"' "$api_body"; then
  echo "Vercel API rewrite failed." >&2
  exit 1
fi
if ! grep -Eiq '^cache-control:.*no-store' "$api_headers"; then
  echo "Vercel API responses must be marked no-store." >&2
  exit 1
fi
if ! grep -Eiq '^content-security-policy:' "$root_headers"; then
  echo "Vercel security headers are missing." >&2
  exit 1
fi

oauth_headers="$tmp_dir/oauth-headers"
oauth_status="$(curl -sS --dump-header "$oauth_headers" --output /dev/null --write-out '%{http_code}' "$VERCEL_URL/api/auth/spotify/start?return_to=%2Fdiscover")"
if [[ "$oauth_status" != "302" ]] || ! grep -Eiq '^location: https://accounts\.spotify\.com/authorize' "$oauth_headers"; then
  echo "Spotify OAuth start did not survive the Vercel rewrite." >&2
  exit 1
fi

if grep -ERiq 'SUPABASE_DB_URL|SPOTIFY_APP_CLIENT_SECRET|postgres(ql)?://' web/dist; then
  echo "Frontend build output contains a privileged value marker." >&2
  exit 1
fi

printf 'Vercel deployment verified: %s\n' "$VERCEL_URL"
