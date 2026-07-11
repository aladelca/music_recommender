# ADR 0001: Vercel Frontend, AWS Backend, Supabase Persistence

- Status: Accepted
- Date: 2026-07-10
- Product: Outside the Loop

## Context

The existing repository deploys a single-user FastAPI API on AWS and reads recommender datasets from
local files or private S3. The beta needs a browser product, per-user Spotify login, relational
ownership, explicit user inputs, automated independent music discovery, and review-first playlist
export for five testers.

Spotify policy prevents using Spotify profile/content analysis as the recommendation data source.
The product owner also requires that the new product not use local or S3 catalog files.

## Decision

### Public Web Layer

- Deploy a React, TypeScript, and Vite application to Vercel.
- Use the stable Vercel production domain for the Spotify redirect URI.
- Proxy browser `/api/*` requests to AWS API Gateway with a Vercel external rewrite.
- Do not add CloudFront. Vercel already provides the frontend edge, and API Gateway is the backend
  edge.

### Trusted Backend

- Keep FastAPI/Mangum on AWS Lambda behind API Gateway.
- Implement Spotify authorization-code OAuth, application sessions, authorization, CSRF, playlist
  export, recommendation orchestration, and external API clients in AWS.
- Use AWS KMS for refresh-token encryption and Secrets Manager for backend credentials.
- Use SQS workers for external API expansion and retries after local acceptance.

### Product Persistence

- Use Supabase Postgres through its TLS transaction pooler.
- Keep database credentials backend-only; the browser does not use Supabase Auth or Data APIs.
- Store users, sessions, explicit seeds, recommendation sessions/items/evidence, feedback, playlist
  exports, evaluations, and normalized external API caches in Postgres.
- Use relational constraints and account-scoped repositories as the primary integrity boundary.

### Automated Music Data

- Search and normalize explicit artist/recording inputs through MusicBrainz.
- Generate candidates through ListenBrainz artist/tag radio and optional experimental recording
  similarity.
- Cache normalized entities, candidate edges, source evidence, and export mappings in Supabase.
- Perform no product reads from local catalog files or S3.
- Use Spotify only for account identity, attributed links/display, and explicit playlist writes.
- Keep ReccoBeats disabled for product routes because its foundational metadata is Spotify-derived.

## Request Flow

```text
Browser -> Vercel -> /api rewrite -> API Gateway -> FastAPI Lambda
                                                    |-> Supabase Postgres
                                                    |-> MusicBrainz API
                                                    |-> ListenBrainz API/Labs
                                                    |-> Spotify OAuth/Web API
                                                    |-> AWS KMS/Secrets Manager
```

Recommendation requests first read a fresh Supabase cache. Missing or stale data creates an
asynchronous discovery job. Workers obey source rate limits, write normalized results, and allow the
client to retry/poll. A source outage never falls back to repository files or S3.

## Consequences

### Positive

- The recommendation boundary is compatible with the accepted Spotify policy assessment.
- The product has one relational source of truth and no catalog artifact deployment process.
- External facts retain source, fetched time, expiry, and evidence provenance.
- Same-origin browser requests support secure cookies without a separate CloudFront distribution.
- The legacy S3/DynamoDB demo can remain isolated for rollback while product routes are developed.

### Negative

- Product quality and latency depend on third-party APIs.
- MusicBrainz's one-request-per-second limit requires distributed throttling and aggressive caching.
- ListenBrainz Labs endpoints are experimental and need feature flags and fallbacks.
- Supabase is an additional cloud dependency outside AWS.
- Recommender sessions may initially return a queued state while data is populated.

## Rejected Alternatives

- Spotify profile synchronization: rejected by the policy assessment.
- Local or S3 catalogs: rejected by the product owner for the new product runtime.
- Supabase Auth: rejected because Spotify refresh-token custody and rotation still require trusted
  backend handling.
- DynamoDB for all product state: rejected because the required ownership, cache, history,
  evaluation, and cleanup relationships are better expressed with Postgres constraints.
- CloudFront: rejected because it duplicates Vercel's frontend edge without solving a beta
  requirement.
- Live API calls without caching: rejected because of latency, outages, and source rate limits.
- ReccoBeats as a core source: rejected for this beta because its terms identify Spotify-derived
  foundational metadata and transfer third-party compliance responsibility to the caller.

## Rollback

- Keep the current single-user stack and retained DynamoDB resources unchanged during local work.
- Product routes remain disabled until Supabase migrations and local security tests pass.
- If an external source becomes unavailable, disable that adapter and return a source-unavailable
  state; do not silently switch to Spotify analysis, local files, or S3.
- If Supabase is unavailable after deployment, disable product login/recommendation writes and
  restore from its backup rather than dual-writing to DynamoDB.
