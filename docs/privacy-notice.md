# Outside the Loop Beta Privacy Notice

Last updated: 2026-07-10

Outside the Loop is a private five-tester music-discovery beta. The contact address must be set to
`[PRIVACY_CONTACT_EMAIL_REQUIRED_BEFORE_BETA]` before inviting testers.

## Data We Process

- Spotify account identifier and display name read under `user-read-private`, granted playlist-write
  scopes, encrypted refresh token, and login timestamps. Subscription, country, and explicit-content
  profile fields are not retained.
- Opaque application sessions and one-time OAuth state. Browser cookies contain opaque random
  values, not Spotify tokens.
- MusicBrainz artist or recording seeds explicitly selected by the user.
- User-authored discovery prompts and explicit familiar/balanced/adventurous controls.
- MusicBrainz and ListenBrainz entity, tag, candidate-edge, listener-count, source-version, and
  cache-expiry data obtained through their public HTTPS APIs.
- Spotify track IDs and bounded display fields resolved only after independent ranking, plus the
  reviewed playlist name, visibility, order, playlist ID, and export status.
- Recommendation snapshots, structured evidence, likes/dislikes/hides/saves/skips, account-only
  blocked MBIDs, and optional beta evaluation ratings/comments.

The product does not read Spotify top items, saved library, recently played history, or existing
playlists. It does not use Spotify profile/listening data for recommendation scoring. It does not
read or deploy local, S3, CSV, or Parquet catalog data. Feedback from the five testers is not pooled
into a shared ranker.

## Purpose And External Services

Data is used to authenticate the tester, generate and explain recommendations from explicit seeds,
export a reviewed playlist to that tester's Spotify account, operate the beta, and evaluate whether
recommendations are better than the tester's usual Spotify discovery experience.

- Spotify processes sign-in, bounded post-ranking track lookup, attributed links, and playlist
  writes under its own terms.
- MusicBrainz processes bounded search requests for explicit seed text.
- ListenBrainz processes seed artist MBIDs and bounded tag/metadata requests. No Spotify account ID
  or token is sent to ListenBrainz.
- AWS processes API/Lambda/SQS/KMS operations and operational logs.
- Supabase hosts backend-only Postgres records. The browser receives no Supabase credential.
- Vercel hosts the frontend and same-origin API rewrite.

## Retention And Security

- OAuth state expires after 10 minutes; expired or consumed state is cleaned automatically.
- Application sessions expire after 7 days idle and 30 days absolute; old revoked rows are cleaned.
- Positive source caches expire after at most 30 days depending on record type; negative lookups
  expire after one hour; expired candidate edges and Spotify mappings are cleaned.
- Completed discovery jobs are retained up to 30 days.
- Removed seed rows are retained up to 30 days.
- Recommendation sessions, evidence, feedback, evaluations, and export records are retained up to
  180 days for the beta unless the user deletes the account earlier.
- Spotify refresh tokens are encrypted with an account-bound AWS KMS context and are never returned
  to the browser or written to logs.

Operational logs must not include prompts tied to account identifiers, cookies, authorization
headers, Spotify tokens, raw provider payloads, or evaluation comments.

## Deletion

An authenticated tester can delete the account from settings by confirming `DELETE`. The backend
hard-deletes the account row in one transaction; Postgres cascades application sessions, encrypted
token ciphertext, seeds, preferences, recommendation sessions/items, feedback, playlist export
records, and evaluations. Shared expired source-cache records are removed by scheduled retention.
The application clears its authentication cookies after deletion.

Deletion from Outside the Loop does not delete a playlist already created in Spotify. The tester
can remove that playlist in Spotify. A deleted tester may sign in again later only as a new pending
beta account requiring administrator approval.

## Tester Choices

Testers can choose explicit-content handling, remove/reorder every playlist track before export,
choose public or private visibility, skip feedback/evaluation comments, log out, or delete the
account. Questions and deletion problems should be sent to the beta contact address listed above.
