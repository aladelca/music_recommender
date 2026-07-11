# Outside the Loop Beta Acceptance

## Product Scope

Outside the Loop is an explainable music-discovery beta for five Spotify Development Mode users.
It recommends music from explicit session inputs and independent online music APIs, lets the user
review the result, and exports the reviewed tracks to the authenticated Spotify account.

The beta is product validation, not monetization or a claim of statistical superiority.

## Required User Flow

1. The user signs in with Spotify and is pending until internally approved.
2. The user searches MusicBrainz and selects one to five artist or recording seeds.
3. The user enters a discovery prompt and chooses familiar, balanced, or adventurous mode.
4. The backend resolves and expands candidates through MusicBrainz and ListenBrainz APIs.
5. The product shows ten recommendations with source-backed evidence and limitations.
6. The user listens through an attributed Spotify link/embed, removes tracks, and reorders the set.
7. The user explicitly names the playlist, chooses public or private, and confirms export.
8. The playlist appears in the same Spotify account used to sign in.
9. The user records whether the result was better, the same, worse, or uncertain compared with
   their usual Spotify discovery experience.

## Functional Acceptance

- Exactly five accounts can be approved; unknown accounts remain pending by default.
- Recommendation ownership comes only from the application session, never a request user ID.
- No product endpoint reads Spotify top items, saved items, recent plays, or playlist contents.
- Seed search, candidate retrieval, metadata, and mappings are automated HTTPS calls.
- Supabase stores all product records and caches; product runtime does not read local or S3 data.
- External API failures produce retryable or degraded states rather than invented tracks.
- Every recommendation has at least one verifiable reason and an honest coverage limitation.
- Recommendation generation has no Spotify write side effect.
- Playlist export requires a reviewed ordered track list, explicit name, visibility, and idempotency
  key.
- Cross-account reads and writes return `404` and leave data unchanged.
- Disconnect/account deletion revokes sessions and deletes account-owned product data.

## Quality Acceptance

- Ruff formatting/lint, mypy, and the complete Python test suite pass.
- Supabase migrations apply from an empty database and enforce ownership, uniqueness, and the
  five-user approval limit.
- Frontend lint, type checks, component tests, production build, and Playwright flows pass.
- Security tests cover OAuth state replay, open redirects, CSRF, session expiry/fixation, tenant
  isolation, token redaction, SQL injection, and idempotency conflicts.
- MusicBrainz calls are globally throttled to one per second and all external clients honor retry
  limits and timeouts.
- Lambda and Vercel artifacts contain no `.parquet`, `.csv`, `.env`, local catalog, or credential
  files.

## Local-First Gate

Cloud resources are not created or changed until all local tests and builds pass. Local integration
uses a Supabase CLI database and mocked MusicBrainz, ListenBrainz, Spotify, and KMS boundaries.

After local acceptance, deployment uses a scoped IAM/GitHub OIDC role. It must not use AWS root
credentials. The first live acceptance uses the product owner; four beta approvals remain pending.

## Beta Success Criteria

- Five testers complete at least three prescribed discovery sessions each when they become
  available.
- At least four testers prefer Outside the Loop in a majority of their rated sessions.
- Median explanation usefulness is at least 4/5.
- Each tester accepts at least 20% of recommendations across the prescribed sessions.
- No known policy violation, cross-tenant access, incorrect playlist owner, or unexplained evidence
  claim remains open.

With only five users, report counts, medians, and per-user ranges. Do not present statistical
significance or broad market claims.

## Release Stop Conditions

- Spotify policy scope expands beyond identity and playlist export.
- A ranking path consumes Spotify-derived profile, popularity, audio, or metadata features.
- MusicBrainz/ListenBrainz terms or availability no longer support the automated path.
- Supabase credentials or Spotify tokens reach browser code, logs, artifacts, or test fixtures.
- The second-user isolation test fails once another tester is available.
