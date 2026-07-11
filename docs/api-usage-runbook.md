# Product API Usage Runbook

Outside the Loop is a browser-session API exposed through the Vercel production origin. Use
`https://<project>.vercel.app/api` as the API base. Calls made directly to API Gateway use the same
paths without `/api`, but normal clients should use Vercel so OAuth cookies remain same-origin.

There is no product API key. `RECOMMENDER_API_KEY` and `X-API-Key` belong only to the disabled
legacy demo. Product ownership is derived from the authenticated `__Host-mr_session` cookie; a
caller cannot choose a Spotify user or account ID in request JSON.

## Authentication

Open this URL in a browser:

```text
https://<project>.vercel.app/api/auth/spotify/start?return_to=/discover
```

After Spotify consent, the callback creates or updates a pending account and sets:

- `__Host-mr_session`: secure, HTTP-only opaque application session.
- `__Host-mr_csrf`: secure double-submit CSRF token readable by the frontend.

The first login is pending until an operator approves the Spotify account. After approval, sign in
again or refresh `/auth/me`. The playlist is always created in the same Spotify account used to sign in. Spotify top items, saved tracks, recent plays, and playlists are not read.

Check the session:

```bash
export APP_ORIGIN=https://<project>.vercel.app
export API_BASE="$APP_ORIGIN/api"
curl -fsS --cookie-jar /tmp/outside-loop-cookies "$API_BASE/auth/me" | jq .
```

The browser is the supported OAuth client. For curl or Postman, first sign in through the browser,
then import its two opaque Outside the Loop cookies into a private local cookie jar. Never share or
commit either value. A mutation must send both cookies, an exact `Origin`, and `X-CSRF-Token` equal
to the decoded `__Host-mr_csrf` cookie.

For curl, create a mode-restricted header file without printing values:

```bash
umask 077
export SESSION_COOKIE='<value from browser cookie storage>'
export CSRF_TOKEN='<decoded __Host-mr_csrf value>'
export AUTH_HEADERS="$(mktemp)"
trap 'rm -f "$AUTH_HEADERS"; unset SESSION_COOKIE CSRF_TOKEN' EXIT
printf 'Cookie: __Host-mr_session=%s; __Host-mr_csrf=%s\nOrigin: %s\nX-CSRF-Token: %s\n' \
  "$SESSION_COOKIE" "$CSRF_TOKEN" "$APP_ORIGIN" "$CSRF_TOKEN" > "$AUTH_HEADERS"
```

GET requests require only the session cookie; using the same header file for examples is safe.

## Postman Setup

1. Create `app_origin` as the exact Vercel origin and `api_base` as `{{app_origin}}/api`.
2. In Postman's cookie manager, add `__Host-mr_session` and `__Host-mr_csrf` for the Vercel host.
3. Create a private environment value `csrf_token` equal to the decoded CSRF cookie.
4. For `POST`, `PUT`, and `DELETE`, add `Origin: {{app_origin}}` and
   `X-CSRF-Token: {{csrf_token}}`.
5. Use `Content-Type: application/json` for JSON bodies. Add `Idempotency-Key` where documented.

Do not put the Spotify client secret, Supabase DSN, refresh token, or an AWS secret in Postman.

## Health And Current User

```bash
curl -fsS "$API_BASE/health" | jq .
curl -fsS "$API_BASE/ready" | jq .
curl -fsS -H "@$AUTH_HEADERS" "$API_BASE/auth/me" | jq .
```

`/health` is shallow. `/ready` checks the backend database and returns `503` without configuration
details when unavailable. Product OpenAPI/docs routes are intentionally disabled.

## Select Explicit Seeds

Search MusicBrainz for an artist or recording. Search text is bounded and is not a Spotify profile
query:

```bash
curl -fsS -H "@$AUTH_HEADERS" --get \
  --data-urlencode 'q=Portishead' \
  --data-urlencode 'type=artist' \
  "$API_BASE/music/search" | jq .
```

Confirm one to five returned MBIDs:

```bash
curl -fsS -X PUT -H "@$AUTH_HEADERS" -H 'Content-Type: application/json' \
  --data '{
    "seeds": [
      {"entity_type": "artist", "mbid": "8ab7aa79-24a4-4a5f-b2c6-3e3c2c7af95c"}
    ]
  }' \
  "$API_BASE/me/seeds" | tee /tmp/outside-loop-seeds.json | jq .
```

The returned seed `id` is an application UUID; recommendation requests use that ID, not the MBID.

## Populate Automated Discovery Data

`POST /api/discovery/jobs` queues MusicBrainz/ListenBrainz expansion from the current user's seeds:

```bash
curl -fsS -X POST -H "@$AUTH_HEADERS" \
  "$API_BASE/discovery/jobs" | tee /tmp/outside-loop-job.json | jq .

export JOB_ID="$(jq -er '.id' /tmp/outside-loop-job.json)"
curl -fsS -H "@$AUTH_HEADERS" \
  "$API_BASE/discovery/jobs/$JOB_ID" | jq .
```

Poll with bounded delay until `status` is `ready`, `degraded`, or `failed`. A retryable source
outage never falls back to local files or S3.

## Get Recommendations

`POST /api/me/recommendations` generates and snapshots an account-owned result:

```bash
export SEED_ID="$(jq -er '.seeds[0].id' /tmp/outside-loop-seeds.json)"

jq -n --arg seed_id "$SEED_ID" '{
  prompt: "Atmospheric trip hop for late-night focus",
  adventure: "balanced",
  allow_explicit: false,
  seed_ids: [$seed_id]
}' > /tmp/outside-loop-recommendation-request.json

curl -fsS -X POST -H "@$AUTH_HEADERS" -H 'Content-Type: application/json' \
  --data @/tmp/outside-loop-recommendation-request.json \
  "$API_BASE/me/recommendations" \
  | tee /tmp/outside-loop-recommendation.json \
  | jq '{id, status, ranking_version, source_coverage, recommendations}'
```

The accepted values for `adventure` are `familiar`, `balanced`, and `adventurous`. Recommendation
generation is read-only with respect to Spotify. There is deliberately no `create_playlist` field.
Every result contains structured evidence and limitations; Spotify IDs are resolved only after the
independent ranking is complete.

## Review And Name The Playlist

The review request selects and orders one to ten recommendation MBIDs. It also freezes the exact
playlist name and visibility that the export must match:

```bash
export SESSION_ID="$(jq -er '.id' /tmp/outside-loop-recommendation.json)"
jq '{
  recording_mbids: [.recommendations[0:5][].recording_mbid],
  playlist_name: "Late Night Outside the Loop",
  public: true
}' /tmp/outside-loop-recommendation.json > /tmp/outside-loop-review.json

curl -fsS -X PUT -H "@$AUTH_HEADERS" -H 'Content-Type: application/json' \
  --data @/tmp/outside-loop-review.json \
  "$API_BASE/me/recommendations/$SESSION_ID/selection" \
  | tee /tmp/outside-loop-reviewed.json | jq .
```

## Export To Spotify

This is the only recommendation workflow that creates a playlist. `name`, `public`, and ordered
`recording_mbids` must equal the reviewed values. Use a new stable idempotency key for one logical
export and reuse it only when retrying the identical payload:

```bash
export IDEMPOTENCY_KEY="$(uuidgen | tr '[:upper:]' '[:lower:]')"
jq '{
  name: .review.playlist_name,
  description: "Created from reviewed Outside the Loop recommendations",
  public: .review.public,
  recording_mbids: [.recommendations[] | select(.selected) | .recording_mbid]
}' /tmp/outside-loop-reviewed.json > /tmp/outside-loop-export.json

curl -fsS -X POST -H "@$AUTH_HEADERS" -H 'Content-Type: application/json' \
  -H "Idempotency-Key: $IDEMPOTENCY_KEY" \
  --data @/tmp/outside-loop-export.json \
  "$API_BASE/me/recommendations/$SESSION_ID/playlist" | jq .
```

HTTP `201` means a new export completed; `200` with `idempotent_replay: true` means the identical
operation was already completed. Open `spotify_playlist_url` to verify the explicit name,
visibility, order, and owner in Spotify. A partial failure is persisted so retry cannot silently
create duplicates.

Postman raw export body:

```json
{
  "name": "Late Night Outside the Loop",
  "description": "Created from reviewed Outside the Loop recommendations",
  "public": true,
  "recording_mbids": ["<reviewed-recording-mbid>"]
}
```

## Feedback, Evaluation, And History

Record account-scoped item feedback:

```bash
export RECORDING_MBID="$(jq -er '.recommendations[0].recording_mbid' /tmp/outside-loop-recommendation.json)"
curl -fsS -X POST -H "@$AUTH_HEADERS" -H 'Content-Type: application/json' \
  -H "Idempotency-Key: feedback-$SESSION_ID-$RECORDING_MBID-like" \
  --data "{\"recording_mbid\":\"$RECORDING_MBID\",\"event_type\":\"like\"}" \
  "$API_BASE/me/recommendations/$SESSION_ID/feedback" | jq .
```

Save the frozen beta evaluation:

```bash
curl -fsS -X PUT -H "@$AUTH_HEADERS" -H 'Content-Type: application/json' \
  --data '{
    "comparison": "better",
    "explanation_usefulness": 5,
    "novelty_quality": 4,
    "comment": null
  }' \
  "$API_BASE/me/recommendations/$SESSION_ID/evaluation" | jq .

curl -fsS -H "@$AUTH_HEADERS" "$API_BASE/me/recommendations?limit=20" | jq .
```

## Logout And Deletion

```bash
curl -fsS -X POST -H "@$AUTH_HEADERS" "$API_BASE/auth/logout"

curl -fsS -X DELETE -H "@$AUTH_HEADERS" -H 'Content-Type: application/json' \
  --data '{"confirmation":"DELETE"}' "$API_BASE/auth/me"
```

Deletion removes account-owned application data and encrypted token ciphertext. It does not delete
playlists already present in Spotify.

## Security And Error Contract

- `401`: missing, expired, or revoked application session.
- `403`: pending/revoked beta access, Origin failure, CSRF failure, or Spotify permission failure.
- `404`: unknown or Cross-account seed/session/item IDs. The API does not reveal other users' data.
- `409`: review/idempotency conflict or Spotify reconnection required.
- `422`: schema validation failure or forbidden extra field.
- `502/503`: bounded Spotify/source/database failure with a stable `code`.

Capture `X-Request-ID`, status, route, and stable error `code` when reporting an incident. Never
attach cookies, headers, prompts tied to an account, tokens, provider payloads, or free-text comments.
