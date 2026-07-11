# Outside the Loop Recommender Architecture

## Objective

Outside the Loop is an explainable music-discovery product for a five-user beta. A user signs in
with Spotify, explicitly chooses artist or recording seeds, describes the desired listening
session, reviews evidence-backed recommendations, and exports the selected order to their own
Spotify account.

The recommendation engine is deterministic and auditable. Spotify is an identity, attribution, and
playlist-export integration, not the source of taste profiles or ranking features.

## Product Boundary

The product must:

- Use explicit user choices rather than Spotify top, saved, recent, or playlist history.
- Retrieve music entities and candidates from automated independent HTTPS APIs.
- Persist product state and external API caches only in Supabase Postgres.
- Avoid local and S3 catalog files in every product runtime path.
- Render evidence from stored source facts rather than LLM-generated claims.
- Require review and confirmation before any Spotify playlist write.

The detailed policy decision is in `docs/spotify-policy-assessment.md`.

## User Flow

1. The user authenticates with Spotify and receives an application session.
2. An administrator approves the pending account within the five-user limit.
3. The user searches for one to five artist or recording seeds.
4. MusicBrainz resolves the search to stable artist/recording MBIDs.
5. The user enters a prompt and chooses adventure and explicit-content controls.
6. ListenBrainz artist/tag APIs expand the explicit seeds into candidate recording MBIDs.
7. The backend filters, ranks, diversifies, and builds evidence from independent source facts.
8. The user removes and reorders tracks and explicitly names the playlist.
9. The backend maps selected MBIDs to Spotify IDs, creates `/me/playlists`, and adds `/items`.
10. The user rates recommendation and explanation quality.

## Automated Data Sources

### MusicBrainz

MusicBrainz supplies canonical artist/recording identity, search, credits, release dates, tags, and
ISRCs. The client sends a contactable application `User-Agent`, makes at most one request per second
across the deployment, and caches results in Supabase.

### ListenBrainz

ListenBrainz supplies independent collaborative discovery:

- Artist seeds: `GET /1/lb-radio/artist/{seed_artist_mbid}`.
- Seed and parsed-prompt tags: `GET /1/lb-radio/tags`.
- Recording seeds: artist radio for MusicBrainz-credited artists.
- Recording title, artist credit, ISRC, release, and tag evidence: `POST /1/metadata/recording/`.
- Spotify export mapping: resolve a ranked recording MBID only after ranking.

The client honors rate-limit headers, uses bounded retries, and stores source, fetched time,
algorithm/version, and expiry with every cache entry. Experimental ListenBrainz Labs datasets are
disabled in the beta path; enabling them later requires an explicit feature and coverage review.

### Spotify

Spotify supplies:

- OAuth account identity.
- Attributed links, embeds, and permitted display metadata.
- Public/private playlist creation for the current user.
- Addition of reviewed track IDs to the created playlist.

Product code does not call Spotify top, library, recently played, or playlist-read endpoints.

### ReccoBeats

ReccoBeats remains legacy and disabled for product routes. Its own terms identify Spotify as the
source of foundational metadata, so it is not needed for the policy-compliant beta.

## Online Architecture

```text
React/Vite on Vercel
  -> same-origin /api rewrite
    -> API Gateway
      -> FastAPI Lambda
        -> Supabase Postgres
        -> MusicBrainz API
        -> ListenBrainz API and Labs
        -> Spotify Accounts/Web API
        -> KMS and Secrets Manager
      -> SQS discovery worker
      -> scheduled cache cleanup worker
```

CloudFront is not part of the design. Existing S3 and DynamoDB resources belong only to the legacy
single-user deployment and are not queried by product routes.

## Persistence

Supabase contains:

- Application users, encrypted Spotify token references, and access status.
- Hashed application sessions and one-time OAuth state.
- Explicit user-selected seeds and blocked entities.
- Canonical MusicBrainz entities and external identifier mappings.
- ListenBrainz candidate edges, source facts, algorithms, fetch times, and expiries.
- Discovery jobs and redacted external-source errors.
- Recommendation sessions, ordered items, and evidence snapshots.
- Feedback, reviewed selections, playlist exports, and beta evaluations.

The browser has no Supabase credentials. Every user-owned query requires account context from the
server-side application session.

## Recommendation Pipeline

### 1. Resolve Intent

Parse the user-authored prompt into bounded mood/tag/constraint fields. The deterministic parser is
the default. An optional LLM receives only the raw prompt and never receives music metadata or user
history.

### 2. Resolve Seeds

Resolve artist/recording text through MusicBrainz search and require explicit user confirmation.
Store the selected MBID, display label, source, and selection time as first-party input.

### 3. Retrieve Candidates

Use fresh Supabase cache entries when available. Otherwise enqueue source requests:

- Artist radio for each artist seed.
- Artist radio for the credited artist of a recording seed.
- Tag radio for prompt tags.

Merge candidates by recording MBID and retain each source edge.

### 4. Filter

Remove selected seeds, blocked entities, duplicate recordings, disallowed explicit candidates when
the source can establish that fact, and candidates without an export mapping or enough evidence.

### 5. Rank

Version `explicit-discovery-v1` uses only independent and first-party components:

```text
score =
  0.35 * prompt_or_tag_fit
  + 0.30 * seed_bridge_strength
  + 0.20 * discovery_value
  + 0.15 * evidence_quality
```

Familiar/balanced/adventurous shifts at most ten percentage points between bridge strength and
discovery value. Selection enforces artist diversity and deterministic tie-breaking. Exact numeric
scores remain internal.

### 6. Explain

Evidence cards cite:

- The user-selected seed that opened the path.
- The ListenBrainz artist, tag, or recording-similarity edge.
- Independent popularity/listener support when available.
- Prompt/tag alignment.
- A limitation when source coverage or mapping confidence is weak.

Evidence never claims to represent the user's Spotify taste or listening history.

### 7. Review And Export

Recommendation generation is read-only. The user reviews an ordered subset, enters the final
playlist name and visibility, and confirms export with an idempotency key. The backend creates the
playlist in the authenticated account and resumes partial item-add failures without creating a
duplicate playlist.

## Caching And Failure Behavior

- Canonical MusicBrainz entity: 30-day TTL.
- MusicBrainz negative search: 1-hour TTL.
- ListenBrainz candidate and metadata expansion: 7-day positive TTL and 1-hour negative TTL.
- Normalized ListenBrainz recording entity: 30-day TTL.
- Spotify export mapping: 24-hour maximum TTL.

Expired cache is never treated as fresh silently. A source outage returns queued, degraded, or
source-unavailable state. HTTP retries are followed by at most three SQS worker attempts. The
product never falls back to a repository file or S3.

## Scientific Evaluation

The first beta freezes ranking and source versions. Each tester completes three sessions: familiar,
mood/activity, and adventurous. The primary measure is whether the tester rates the session better
than their usual Spotify discovery experience. Secondary measures are selected-track rate,
playlist export, explanation usefulness, source coverage, latency, and evidence complaints.

Five users provide directional product evidence only. Report counts, medians, and per-user ranges,
not statistical significance.

## Sources

- [Spotify Developer Policy](https://developer.spotify.com/policy)
- [MusicBrainz Web Service](https://musicbrainz.org/doc/Development/XML_Web_Service/Version_2)
- [MusicBrainz search](https://musicbrainz.org/doc/MusicBrainz_API/Search)
- [MusicBrainz rate limiting](https://musicbrainz.org/doc/MusicBrainz_API/Rate_Limiting)
- [ListenBrainz API](https://listenbrainz.readthedocs.io/en/latest/users/api/index.html)
- [ListenBrainz core endpoints](https://listenbrainz.readthedocs.io/en/latest/users/api/core.html)
- [ListenBrainz Labs dataset hoster](https://labs.api.listenbrainz.org/)
- [ReccoBeats terms](https://reccobeats.com/docs/documentation/terms-of-service)
