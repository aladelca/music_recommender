# Live Spotify Profile Strengthening

## Source Request

Create an implementation plan for making the live Spotify profile path strong before adding
DynamoDB or other app-owned persistence. The recommender should use the authenticated user's
Spotify data, especially liked/saved songs, through the Spotify API and feed that profile into the
API-only recommendation flow.

## Goals

- Make Spotify the source of truth for live user taste signals in the beta demo.
- Retrieve saved tracks and top tracks/artists robustly through Spotify OAuth.
- Read selected user playlists and playlist items to enrich taste signals and candidate coverage.
- Build a richer `UserTasteProfile` from live Spotify data instead of relying mostly on request
  overrides or a shallow cached JSON snapshot.
- Prove that `/profile/sync` followed by `/recommendations` uses the synced Spotify profile.
- Keep the implementation backend-only and testable without live Spotify calls in CI.
- Preserve local JSON cache behavior for the class demo; do not add DynamoDB for this step.

## Non-Goals

- No DynamoDB or long-term app-owned profile store in this phase.
- No frontend.
- No training or fine-tuning on Spotify data.
- No dependence on Spotify's deprecated recommendations or audio feature endpoints.
- No broad rewrite of the scoring engine or OpenAI agent layer.
- No live Spotify calls in automated tests.

## Assumptions

- `src/music_recommender/sources/spotify_user.py` already has user OAuth token refresh, current
  profile, top items, saved tracks, playlist creation, and playlist item add methods.
- `src/music_recommender/recommender/profile.py` currently syncs only one page each of top tracks,
  top artists, and saved tracks into `UserTasteProfile`.
- `src/music_recommender/api/services.py` already loads the cached profile in recommendation
  requests and merges explicit request-level taste overrides.
- `.env.example` already includes `SPOTIFY_USER_REFRESH_TOKEN`, `SPOTIFY_DEMO_USER_ID`, and
  `SPOTIFY_USER_SCOPES`.
- Spotify's saved tracks endpoint is `GET /me/tracks`, uses `user-library-read`, supports
  `limit`/`offset`, and returns saved-track objects.
- Spotify's top items endpoint is `GET /me/top/{type}`, uses `user-top-read`, supports
  `artists`/`tracks`, `time_range`, `limit`, and `offset`.
- Spotify's current user profile endpoint is `GET /me`; `account_id` is documented as the stable
  account-linking identifier, while `id` should not be treated as immutable.
- Spotify's current user playlists endpoint is `GET /me/playlists`, returns playlists owned or
  followed by the current user, and uses `playlist-read-private` for private playlist access.
- Spotify's playlist items endpoint is `GET /playlists/{playlist_id}/items`, supports paginated
  item reads, and requires the playlist to be owned by the current user or collaborative.
- Recently played data is useful but should be optional because it requires
  `user-read-recently-played`.

## Open Questions

- Should the demo request `user-read-private` so profile sync can read market/explicit-content
  settings, or keep the initial scope set smaller?
- Should the demo request `user-read-recently-played`, or avoid that scope until the saved/top-item
  profile is proven end to end?
- Which playlists should be included by default: all owned/followed playlists up to a cap, only
  user-selected playlist IDs, or playlists whose names match a configured allowlist such as
  favorites/starred/demo?
- Should profile sync fail hard when the authenticated Spotify user ID differs from
  `SPOTIFY_DEMO_USER_ID`, or keep the current fail-hard behavior only for class demo safety?

## Current Repo Context

- `plans/beta-demo-agentic-recommender.md` says Phase 0 still needs a live
  `SPOTIFY_USER_REFRESH_TOKEN` and Phase 3 live profile sync/playlist creation require valid user
  OAuth.
- `src/music_recommender/config.py` defaults `SPOTIFY_USER_SCOPES` to
  `user-top-read user-library-read playlist-modify-private playlist-modify-public`.
- `src/music_recommender/demo_readiness_cli.py` can print an OAuth URL, exchange an authorization
  code, refresh a Spotify user token, and validate configured scopes.
- `src/music_recommender/sources/spotify_user.py` has low-level methods for `get_current_user_profile`,
  `get_top_items`, and `get_saved_tracks`, but no helper for pagination or recently played.
  It also does not yet expose read methods for current user's playlists or playlist items.
- `src/music_recommender/recommender/profile.py` maps Spotify profile data into
  `UserTasteProfile`, but it currently keeps only track IDs and artist names; it does not retain
  source counts, time ranges, playlist signals, recently played signals, track recency, or stable
  account IDs.
- `src/music_recommender/recommender/models.py` defines `UserTasteProfile` with
  `liked_track_ids`, `known_track_ids`, `liked_artist_names`, `blocked_artist_names`,
  `artist_affinity`, and `track_affinity`.
- `src/music_recommender/recommender/scoring.py` already uses liked track IDs, known track IDs,
  liked artist names, `artist_affinity`, and `track_affinity` when ranking.
- `src/music_recommender/api/services.py` reads `JsonProfileCache` during recommendation requests
  and merges request-level `liked_*`, `known_*`, and `blocked_*` overrides.
- `src/music_recommender/api/models.py` exposes `ProfileSyncRequest` with `top_limit`,
  `saved_limit`, and `market`; there is no time-range selection, page cap, or recent-play option.
- `scripts/demo_sync_profile.sh` posts only `top_limit` and `saved_limit`.
- Existing tests use fake Spotify clients and `httpx.MockTransport`; follow that style.

## Backend/API Integration

- Keep existing endpoints:
  - `POST /profile/sync`
  - `GET /profile`
  - `POST /recommendations`
- Extend `ProfileSyncRequest` conservatively:
  - `top_limit`: total target count per top item type, not just one Spotify page.
  - `saved_limit`: total target saved-track count across pages.
  - `top_time_ranges`: default `["short_term", "medium_term", "long_term"]` or a smaller default
    if implementation wants lower latency.
  - `include_playlists`: default `true` for the demo if `playlist-read-private` is granted,
    otherwise degrade gracefully.
  - `playlist_limit`: maximum playlists to inspect.
  - `playlist_track_limit`: maximum playlist tracks to inspect in total or per playlist.
  - `playlist_ids`: optional explicit playlist IDs for a controlled class demo.
  - `include_recently_played`: default `false`.
  - `recently_played_limit`: default `20`, max `50`.
  - `market`: keep existing optional behavior.
- Add or expose Spotify client helpers:
  - `iter_saved_tracks(limit_total, page_size=50, market=None)`
  - `iter_top_items(type, limit_total, time_range, page_size=50)`
  - `iter_current_user_playlists(limit_total, page_size=50)`
  - `iter_playlist_items(playlist_id, limit_total, page_size=50, market=None, fields=None)`
  - Optional: `get_recently_played(limit=20, before=None, after=None)`
- `POST /profile/sync` should return a redacted profile summary with counts and source coverage,
  not raw secrets or overly large Spotify payloads.
- `POST /recommendations` should keep working without live Spotify when request-level overrides are
  provided, but when a cache exists it should use the richer synced profile automatically.
- Keep API key middleware behavior unchanged.

## Data Model And Persistence

- Keep local JSON cache as the persistence mechanism for this phase:
  `RECOMMENDER_PROFILE_CACHE_PATH`, defaulting to `data/local/api_state/profile.json`.
- Do not add DynamoDB or migrations.
- Extend `ProfileSnapshot` payload in a backward-compatible way:
  - Existing `profile` object remains readable.
  - Add optional `spotify_account_id`.
  - Add optional `spotify_user_id`.
  - Add optional `source_counts`, for example saved tracks, top tracks, top artists, recent plays.
  - Add optional `playlist_sources`, for example playlist IDs/names inspected and track counts.
  - Add optional `scope_coverage` or `missing_optional_scopes`.
  - Add optional `time_ranges`.
- Extend `UserTasteProfile` only if needed by scoring:
  - Prefer using existing `artist_affinity` and `track_affinity` for weighted Spotify signals.
  - `liked_track_ids` should represent strong positive signals from saved tracks and top tracks.
  - `known_track_ids` should include saved, top, playlist, and optionally recently played tracks.
  - Playlist tracks should enrich candidate coverage and taste affinity, but should usually have a
    weaker positive weight than saved tracks unless the playlist is explicitly selected as a
    favorite/demo playlist.
- Backward compatibility:
  - `_snapshot_from_payload` must load existing profile JSON files that only contain the current
    fields.
  - Existing recommendation request override behavior must remain unchanged.

## Implementation Tasks

1. [ ] Add paginated Spotify user and playlist read helpers.
   - Files: `src/music_recommender/sources/spotify_user.py`,
     `tests/test_spotify_user_client.py`
   - Notes: Keep current one-shot methods. Add helper methods that request pages with Spotify's
     max page size of 50, stop at the requested total, stop when `items` is empty, and preserve
     bearer-token behavior. Include current-user playlist reads and playlist item reads. Add
     optional `get_recently_played` only behind explicit scope support.

2. [ ] Strengthen profile sync normalization.
   - Files: `src/music_recommender/recommender/profile.py`,
     `tests/test_profile_sync.py`
   - Notes: Build profile signals from multiple pages, time ranges, and selected playlists. Use
     saved tracks as strongest liked-track signal, top tracks as medium/strong affinity, top artists
     as artist affinity, explicitly selected favorite playlist tracks as candidate/affinity signals,
     and optionally recent plays as known-track or light affinity. Deduplicate while preserving
     strongest signal. Avoid storing raw full Spotify payloads.

3. [ ] Extend profile snapshot metadata without breaking old caches.
   - Files: `src/music_recommender/recommender/profile.py`,
     `tests/test_profile_sync.py`
   - Notes: Add source counts, time ranges, playlist source summaries, optional stable account ID,
     and optional Spotify user ID. Ensure old JSON cache payloads still load. Do not store access
     tokens, refresh tokens, or email.

4. [ ] Extend the profile sync API request/response contract.
   - Files: `src/music_recommender/api/models.py`,
     `src/music_recommender/api/services.py`,
     `src/music_recommender/api/routes/profile.py`,
     `tests/test_profile_sync.py`
   - Notes: Add fields for total limits, top time ranges, playlist inclusion/selection, and optional
     recent-play inclusion. Keep existing `top_limit`, `saved_limit`, and `market` valid. Return
     profile and metadata that make it obvious what Spotify sources were used.

5. [ ] Make live profile readiness checks more explicit.
   - Files: `src/music_recommender/demo_readiness_cli.py`,
     `tests/test_*` as appropriate
   - Notes: Add a readiness command or extend `refresh-spotify-token` so it can validate the required
     live profile scopes and optionally fetch a redacted small sample count from `/me/tracks`,
     `/me/top/tracks`, and `/me/playlists` when playlist reads are enabled. Keep token values
     redacted.

6. [ ] Update demo scripts and docs for the live profile flow.
   - Files: `scripts/demo_sync_profile.sh`, `scripts/demo_recommend.sh`, `README.md`,
     `docs/recommender-architecture.md`
   - Notes: Document the sequence: generate OAuth URL, exchange code, save refresh token locally,
     refresh/validate token, sync profile from saved tracks/top items/favorite playlists, request
     recommendations, create playlist. Make clear that DynamoDB is not required for this step.
     Document `playlist-read-private` when private or followed playlists should enrich the profile.

7. [ ] Add a focused live-profile integration test path with fakes.
   - Files: `tests/test_profile_sync.py`, `tests/test_recommendations_api.py`,
     possibly `tests/test_spotify_user_client.py`
   - Notes: Cover `sync_profile` with multi-page saved tracks, multiple top time ranges, playlist
     tracks, duplicated tracks/artists, empty saved library, inaccessible playlists, and
     recommendation calls using cached profile affinities.

8. [ ] Update the master plan status.
   - Files: `plans/beta-demo-agentic-recommender.md`
   - Notes: Add a Phase 4 note that the immediate next step is strengthening live Spotify profile
     sync and local cache integration before considering DynamoDB-backed runtime state.

## Tests And Scenarios

- Unit tests:
  - `tests/test_spotify_user_client.py` for paginated saved tracks, paginated top items, optional
    current-user playlists, playlist items, recently played, token reuse, query params, and max
    page-size behavior.
  - `tests/test_profile_sync.py` for deduplication, affinity weighting, source counts, playlist
    source summaries, time ranges, old-cache compatibility, required-user mismatch, inaccessible
    playlists, and empty library/top-item/playlist payloads.
- Integration tests:
  - `tests/test_profile_sync.py` API route coverage for new `ProfileSyncRequest` fields and redacted
    profile summary.
  - `tests/test_recommendations_api.py` or a service-level test showing cached Spotify profile
    affinities influence recommendation ranking without request overrides.
- UI/E2E scenarios:
  - None. This remains API-only.
- Regression scenarios:
  - Existing local recommendations still work with request-provided `liked_artist_names`.
  - Existing `music-recommender-demo-readiness auth-url`, `exchange-code`, and
    `refresh-spotify-token` keep their current behavior.
  - Playlist creation remains separate from playlist reads; reading playlists must not create,
    modify, or delete Spotify playlists.
  - Existing playlist creation and feedback tests continue to pass.
  - Tests must not require real `OPENAI_API_KEY`, `SPOTIFY_USER_REFRESH_TOKEN`, or live Spotify API
    access.

## Validation Commands

```bash
uv run pytest tests/test_spotify_user_client.py tests/test_profile_sync.py tests/test_recommendations_api.py
uv run ruff format --check src tests
uv run ruff check src tests
uv run mypy src tests
uv run pytest
```

Manual local validation after implementation, with real secrets only in `.env`:

```bash
uv run music-recommender-demo-readiness refresh-spotify-token
uv run music-recommender-api --host 127.0.0.1 --port 8000
scripts/demo_sync_profile.sh
scripts/demo_recommend.sh
```

## Risks And Rollback

- Risk: Spotify token has insufficient scopes for saved tracks or top items.
  Mitigation: Validate scopes before sync and return a clear redacted error.
  Rollback: Use request-level `liked_artist_names`/`liked_track_ids` overrides for local demo.

- Risk: Paginating too much profile data slows the API route or hits Spotify rate limits.
  Mitigation: Keep conservative defaults, cap limits, and document larger syncs as manual/demo
  setup work.
  Rollback: Reduce default limits to one page and keep the richer sync behind explicit request
  fields.

- Risk: Cached profile JSON shape changes break existing local cache files.
  Mitigation: Make new fields optional and keep `_snapshot_from_payload` backward compatible.
  Rollback: Delete local cache file and resync, or temporarily ignore metadata fields.

- Risk: Recently played scope adds unnecessary privacy/scope surface.
  Mitigation: Keep recently played disabled by default and separate from the required scope list.
  Rollback: Remove the optional recent-play path without affecting saved/top profile sync.

- Risk: Reading all playlists is slow, noisy, or over-personalizes recommendations around old
  playlists.
  Mitigation: Cap playlist and track reads, support explicit playlist IDs, and weight general
  playlist tracks below saved tracks.
  Rollback: Disable playlist reads while keeping saved/top profile sync.

- Risk: Private playlist access requires `playlist-read-private`, which may not be present in the
  existing refresh token.
  Mitigation: Treat playlist reads as scope-gated and return clear missing-scope guidance.
  Rollback: Re-run OAuth with the added scope or skip playlist enrichment.

- Risk: Spotify stable identity fields differ between accounts or scopes.
  Mitigation: Continue using current `id` for the configured class demo check, but store
  `account_id` when available for future account-linking work.
  Rollback: Keep only `spotify_user_id` in the local snapshot.

## Handoff Notes

- The implementation should not reintroduce DynamoDB as a requirement for this step.
- Treat Spotify saved tracks and top items as input signals, not as a model-training dataset.
- Do not print, log, or persist access tokens, refresh tokens, client secrets, or emails.
- Use official Spotify limits and scopes from the Web API docs; keep optional scopes optional.
- Include playlist reads as candidate/profile enrichment, but keep playlist writes only in the
  explicit playlist creation endpoint.
- Keep the profile sync path deterministic enough that tests can verify exact weighted outputs.
- After this plan is implemented, the next useful live demo milestone is: sync real Spotify profile,
  request recommendations using the cached profile, and create a playlist from those results.

## Sources

- `plans/beta-demo-agentic-recommender.md`
- `src/music_recommender/sources/spotify_user.py`
- `src/music_recommender/recommender/profile.py`
- `src/music_recommender/api/services.py`
- `src/music_recommender/recommender/scoring.py`
- `tests/test_spotify_user_client.py`
- `tests/test_profile_sync.py`
- Spotify Web API reference: Get User's Saved Tracks,
  `https://developer.spotify.com/documentation/web-api/reference/get-users-saved-tracks`
- Spotify Web API reference: Get User's Top Items,
  `https://developer.spotify.com/documentation/web-api/reference/get-users-top-artists-and-tracks`
- Spotify Web API reference: Get Current User's Profile,
  `https://developer.spotify.com/documentation/web-api/reference/get-current-users-profile`
- Spotify Web API reference: Get Current User's Playlists,
  `https://developer.spotify.com/documentation/web-api/reference/get-a-list-of-current-users-playlists`
- Spotify Web API reference: Get Playlist Items,
  `https://developer.spotify.com/documentation/web-api/reference/get-playlists-items`
- Spotify Web API reference: Get Recently Played Tracks,
  `https://developer.spotify.com/documentation/web-api/reference/get-recently-played`
