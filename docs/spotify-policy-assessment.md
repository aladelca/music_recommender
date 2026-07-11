# Spotify Policy Assessment

## Decision

Status: **Conditional GO for an explicit-input beta.**

Outside the Loop may proceed only if Spotify data is not analyzed to build a taste profile or
derive recommendation features. Spotify OAuth is limited to application identity and playlist
export. Recommendation inputs come from choices the user makes directly in Outside the Loop, and
candidate generation uses independent APIs.

This assessment is an engineering release gate, not legal advice. The product owner accepted this
scope for the five-user internal beta on 2026-07-10.

## Why The Original Profile Design Is Rejected

The current Spotify Developer Policy says an application must not analyze Spotify Content or the
Spotify Service for any purpose, including creating metrics, functionality, or user profiles. It
also prohibits using the Spotify Platform or Spotify Content to train or otherwise ingest data into
an ML or AI model.

Those restrictions apply to a development-mode beta. The five-user quota is not a policy exception.
The original design based on saved tracks, top artists, top tracks, recent plays, and playlist
history therefore does not pass this release gate.

Outside the Loop must not request or use these scopes for recommendations:

- `user-top-read`
- `user-library-read`
- `user-read-recently-played`
- `playlist-read-private`
- `playlist-read-collaborative`

Existing single-user demo code may retain these integrations for historical compatibility while it
is isolated behind the legacy API mode. New product routes must not call them.

## Approved Product Boundary

### Spotify May Be Used For

- Authorization-code OAuth and stable application account identity.
- `user-read-private` only for account identity through Spotify's current-user profile endpoint;
  country, product, and explicit-content fields are ignored.
- Creating a public or private playlist in the authenticated user's account after explicit review.
- Adding the reviewed Spotify track IDs to that playlist.
- Displaying permitted Spotify metadata or artwork with required attribution and a link back to
  Spotify.
- Opening a Spotify track, album, artist, or playlist URL selected by the user.
- Resolving final export identifiers after ranking, provided Spotify metadata does not become a
  ranking or profiling input.

### Spotify Must Not Be Used For

- Reading or ranking from saved tracks, top items, recent listening, followed artists, or playlist
  contents.
- Computing taste vectors, affinities, novelty, popularity, mood, similarity, or derived user
  metrics from Spotify data.
- Sending Spotify content, metadata, profile responses, playlist data, or derived values to an LLM
  or other ML/AI system.
- Training or evaluating a recommendation model with Spotify Platform data.
- Building a full player or experience that mimics or replaces Spotify.
- Persisting access tokens, raw Spotify responses, artwork, or metadata beyond what is necessary for
  the user-visible workflow.

## Approved Recommendation Inputs

The user provides first-party inputs directly to Outside the Loop:

- One to five artist or recording seeds selected through MusicBrainz-backed search.
- A natural-language session prompt.
- Adventure level, explicit-content preference, and blocked artists.
- Likes, dislikes, hides, skips, review selections, and playlist exports made inside the product.

The application stores these as explicit first-party choices. It must not label them as a complete
Spotify taste profile or imply that they represent the user's entire listening behavior.

## Automated Independent Data Sources

The product does not download or deploy catalog files. It obtains data over HTTPS and caches
normalized records in Supabase Postgres.

### MusicBrainz

- Use the MusicBrainz Web Service for artist and recording search, MBID lookup, ISRC lookup, and
  canonical metadata.
- Identify Outside the Loop with a contactable `User-Agent`.
- Enforce a distributed maximum of one request per second unless MetaBrainz grants a different
  limit.
- Cache successful lookups and negative results in Supabase to avoid repeated requests.

### ListenBrainz

- Use `GET /1/lb-radio/artist/{seed_artist_mbid}` for artist-seed candidate generation.
- Use `GET /1/lb-radio/tags` for prompt/tag candidate generation.
- Use the ListenBrainz Labs similar-recordings endpoint only as an experimental track-seed
  expansion, behind a feature flag and with a stable fallback to artist radio.
- Honor `X-RateLimit-*`, `Retry-After`, and `429` responses.
- Use ListenBrainz/MusicBrainz metadata and popularity only as independent recommendation evidence.
- Map a ranked recording MBID to a Spotify track ID only after ranking, for linking and playlist
  export. The mapping result is not a ranking signal.

### ReccoBeats

ReccoBeats is not in the production data path for this beta. Its May 2026 terms state that its
foundational track metadata is aggregated from Spotify and that users are responsible for
third-party compliance. Its proprietary audio analysis may be reconsidered only after a separate
written policy decision. Existing source code remains legacy and disabled for product routes.

## Storage And Retention

- Supabase Postgres is the only product persistence and cache.
- Do not write product catalog, candidate, profile, or feature data to local files or S3.
- Cache canonical MusicBrainz entities for 30 days, ListenBrainz candidate responses for 24 hours,
  negative lookups for 1 hour, and Spotify export mappings for at most 24 hours.
- Store user-entered seeds and product feedback for the beta retention period or until account
  deletion.
- Do not persist Spotify access tokens. Encrypt refresh tokens with AWS KMS when cloud deployment is
  enabled.

## AI Boundary

- The default parser is deterministic.
- If an LLM parser is enabled later, its request contains only the user's own prompt.
- Candidate metadata, MusicBrainz/ListenBrainz responses, Spotify identifiers, account identity,
  feedback history, and recommendation output do not enter the LLM request.
- Evidence text is rendered deterministically from stored source facts.

## Release Checks

- Product OAuth requests exactly `user-read-private`, `playlist-modify-private`, and
  `playlist-modify-public`. The identity response is limited to account ID and display name and is
  never a recommendation input.
- Product code has no call path to Spotify top, library, recently played, or playlist-read methods.
- Product recommendation tests fail if a Spotify-derived field appears in ranking input.
- Product deployment does not contain local catalog, CSV, or Parquet files and does not require an
  S3 data bucket.
- UI displays Spotify attribution and links whenever Spotify content is shown.
- Privacy documentation explains explicit seeds, external APIs, storage, disconnect, and deletion.

## Sources

- [Spotify Developer Policy](https://developer.spotify.com/policy)
- [Spotify quota modes](https://developer.spotify.com/documentation/web-api/concepts/quota-modes)
- [Spotify February 2026 migration guide](https://developer.spotify.com/documentation/web-api/tutorials/february-2026-migration-guide)
- [MusicBrainz Web Service](https://musicbrainz.org/doc/Development/XML_Web_Service/Version_2)
- [MusicBrainz rate limiting](https://musicbrainz.org/doc/MusicBrainz_API/Rate_Limiting)
- [ListenBrainz API](https://listenbrainz.readthedocs.io/en/latest/users/api/index.html)
- [ListenBrainz core API](https://listenbrainz.readthedocs.io/en/latest/users/api/core.html)
- [ListenBrainz dataset hoster](https://labs.api.listenbrainz.org/)
- [ReccoBeats terms](https://reccobeats.com/docs/documentation/terms-of-service)
