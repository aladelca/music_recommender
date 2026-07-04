# Session Persistence And Playlist Validation

## Source Request

Create an implementation plan for the next recommender milestone after the overall review: persist
recommendation sessions, validate Spotify playlist creation against the recommendation output, and
prepare the local JSON state layer to evolve into DynamoDB-backed runtime state for AWS.

## Goals

- Persist every recommendation response as a session record with prompt, intent, recommended track
  IDs, and enough track metadata to validate later actions.
- Reject playlist creation when the submitted `session_id` does not exist.
- Reject playlist creation when requested track IDs were not returned by that session's
  recommendation output.
- Keep playlist creation idempotent by `session_id`, while also recording playlist outcome back on
  the recommendation session.
- Validate feedback events against known recommendation sessions and recommended tracks when
  possible.
- Keep the first implementation local-demo friendly with JSON stores, while defining a clear
  storage interface that can be backed by DynamoDB in the AWS phase.

## Non-Goals

- No frontend.
- No broad recommender scoring rewrite.
- No feedback-based reranking in this step; feedback can be validated and persisted, but learning
  from feedback is a later feature.
- No requirement to deploy AWS in the same change.
- No OpenAI agent prompt or orchestration changes unless tests show session persistence needs small
  response-shape adjustments.
- No storage of Spotify access tokens, refresh tokens, OpenAI API keys, or client secrets in session
  records.

## Assumptions

- `POST /recommendations` already returns `session_id`, intent, recommendations, score breakdowns,
  and optional `playlist_candidate` from `AgenticRecommendationService`.
- `DemoApiService.recommend` is the right place to persist sessions because it has the full API
  request, loaded catalog IDs, merged profile context, and final recommendation response.
- `POST /playlists` currently accepts arbitrary `session_id` and `track_ids`; validation must be
  added before calling Spotify playlist creation.
- Existing local JSON stores in `src/music_recommender/recommender/playlists.py`,
  `src/music_recommender/recommender/feedback.py`, and
  `src/music_recommender/recommender/profile.py` establish the local persistence pattern.
- The AWS SAM template already provisions `SESSIONS_TABLE_NAME` and `FEEDBACK_TABLE_NAME`, but
  runtime code does not yet use DynamoDB. A repository-style interface should make a later DynamoDB
  adapter small.
- Automated tests must continue to avoid live Spotify, OpenAI, and AWS calls.

## Open Questions

- Should feedback for tracks outside a recommendation session be rejected immediately, or stored as
  generic session-level feedback? Initial recommendation: reject unknown session IDs and unknown
  track IDs for stronger demo integrity.
- Should playlist creation support a subset of recommended tracks only, or require exactly the
  current `playlist_candidate.track_ids` order? Initial recommendation: allow any non-empty subset
  of the session's recommended track IDs, preserving caller order.
- Should old session records expire locally? Initial recommendation: no TTL for local JSON; add TTL
  only when the DynamoDB adapter is implemented.

## Current Repo Context

- `src/music_recommender/api/services.py` currently builds recommendations, creates playlists, and
  records feedback directly. It uses local state path helpers such as
  `RECOMMENDER_PLAYLIST_STORE_PATH` and `RECOMMENDER_FEEDBACK_STORE_PATH`.
- `src/music_recommender/agents/orchestrator.py` generates a UUID `session_id` and returns
  recommendation payloads through `AgenticRecommendationResponse.to_dict()`.
- `src/music_recommender/recommender/playlists.py` has `JsonPlaylistRecordStore` and
  `PlaylistService`, with idempotency by `session_id`.
- `src/music_recommender/recommender/feedback.py` has `JsonFeedbackStore` and `FeedbackService`,
  but feedback is not validated against recommendation sessions.
- `src/music_recommender/api/models.py` defines `RecommendationRequest`, `PlaylistCreateRequest`,
  and `FeedbackRequest`; no new public fields are required for the first version.
- `tests/test_recommendations_api.py` already verifies recommendation responses with session IDs.
- `tests/test_playlists_api.py` covers playlist endpoint behavior and playlist idempotency, but not
  session-backed track validation.
- `tests/test_feedback_api.py` covers local feedback persistence, but not session-backed feedback
  validation.
- `infra/template.yaml` provisions DynamoDB user, session, and feedback tables and passes table
  names to Lambda, but service code still uses local JSON stores.
- `README.md` documents the current manual demo flow: sync profile, request recommendations, then
  create a Spotify playlist from selected track IDs.

## Backend/API Integration

- Keep existing endpoints:
  - `POST /recommendations`
  - `POST /playlists`
  - `POST /feedback`
- `POST /recommendations` should persist a session before returning the response. If session
  persistence fails, return a 503-style configuration/service error instead of returning a
  playlistable `session_id` that cannot later be validated.
- `POST /playlists` should:
  - Load the session by `session_id`.
  - Return a client error if the session does not exist.
  - Validate every requested track ID is present in the session's recommendation IDs.
  - Preserve existing Spotify playlist creation behavior after validation.
  - Mark the session with playlist ID, URL, requested tracks, added tracks, snapshot ID, and partial
    failures after the Spotify call completes.
- `POST /feedback` should:
  - Load the session by `session_id`.
  - Return a client error if the session does not exist.
  - Validate the feedback `track_id` belongs to the session's recommendation IDs for track-level
    events.
  - Keep existing `FeedbackService` persistence after validation.
- Error handling should use an explicit API error type mapped to 400 or 404, rather than leaking
  `ValueError` through FastAPI as a 500.
- No auth contract change is required. Existing `RECOMMENDER_API_KEY` middleware remains unchanged.

## Data Model And Persistence

- Add a new local session model, likely in `src/music_recommender/recommender/sessions.py`.
- Recommended session fields:
  - `session_id`
  - `user_id`
  - `prompt`
  - `intent`
  - `recommended_track_ids`
  - `recommendations`: compact list of track metadata, score, explanation, and rank
  - `catalog_run_id`
  - `interaction_run_id`
  - `profile_source` or `profile_synced_at` when available
  - `playlist_candidate`
  - `playlist_result`
  - `created_at`
  - `updated_at`
- Add `JsonRecommendationSessionStore` with `get(session_id)`, `put(session)`, and
  `update_playlist_result(...)`.
- Add `RECOMMENDER_SESSION_STORE_PATH`, defaulting through the existing `_state_path()` helper to
  local JSON under `data/local/api_state/`.
- Keep JSON format backward-tolerant: loading should ignore unknown fields and validate required
  fields.
- Define a small `RecommendationSessionStore` protocol so a future DynamoDB adapter can be added
  without changing API service logic.
- DynamoDB adapter is explicitly a follow-on phase:
  - Use `SESSIONS_TABLE_NAME` for sessions.
  - Use `FEEDBACK_TABLE_NAME` for feedback.
  - Store one item per recommendation session keyed by `session_id`.
  - Store feedback events under `session_id` with sortable event keys.

## Implementation Tasks

1. [ ] Add session domain models and JSON store.
   - Files: `src/music_recommender/recommender/sessions.py`,
     `tests/test_recommendation_sessions.py`
   - Notes: Follow the dataclass and JSON serialization style from
     `recommender/playlists.py` and `recommender/feedback.py`. Include helpers to extract
     recommended track IDs and validate requested track subsets.

2. [ ] Add API error types for client validation failures.
   - Files: `src/music_recommender/api/errors.py`, `tests/test_recommendations_api.py`,
     `tests/test_playlists_api.py`, `tests/test_feedback_api.py`
   - Notes: Add something like `ApiValidationError` for 400 and `ApiNotFoundError` for 404.
     Preserve `ApiConfigurationError` as 503.

3. [ ] Persist recommendation sessions from `POST /recommendations`.
   - Files: `src/music_recommender/api/services.py`, `tests/test_recommendations_api.py`
   - Notes: After `AgenticRecommendationService.recommend(...)` returns, convert the response into a
     `RecommendationSession` and save it. Include request `catalog_run_id` and
     `interaction_run_id` resolved values. Tests should use temp session store paths and verify the
     saved session contains the response track IDs.

4. [ ] Validate playlist creation against persisted sessions.
   - Files: `src/music_recommender/api/services.py`,
     `src/music_recommender/recommender/playlists.py`, `tests/test_playlists_api.py`
   - Notes: Prefer keeping Spotify side effects inside `PlaylistService`; do session lookup and
     track validation in a session-aware application service method before calling it. Preserve
     existing idempotency by `session_id`.

5. [ ] Record playlist outcome on the recommendation session.
   - Files: `src/music_recommender/recommender/sessions.py`,
     `src/music_recommender/api/services.py`, `tests/test_playlists_api.py`
   - Notes: Store playlist ID, URL, added tracks, snapshot ID, idempotent replay flag, partial
     failures, and updated timestamp. On idempotent replay, avoid duplicating playlist result state.

6. [ ] Validate feedback against persisted sessions.
   - Files: `src/music_recommender/api/services.py`,
     `src/music_recommender/recommender/feedback.py`, `tests/test_feedback_api.py`
   - Notes: Reject unknown session IDs and track IDs outside the recommendation. Keep feedback store
     behavior unchanged after validation. Do not implement feedback reranking here.

7. [ ] Update local scripts and README flow notes.
   - Files: `README.md`, `scripts/demo_create_playlist.sh`
   - Notes: Document that `SESSION_ID` and `TRACK_IDS_JSON` must come from a recommendation response.
     Mention that playlist creation will now fail for unknown sessions or non-recommended tracks.

8. [ ] Add AWS follow-up notes without wiring DynamoDB yet.
   - Files: `plans/beta-demo-agentic-recommender.md`, `infra/README.md`
   - Notes: Mark session validation as the immediate local/runtime state step before DynamoDB.
     Document that DynamoDB adapter remains pending unless implemented in the same PR.

## Tests And Scenarios

- Unit tests:
  - Add `tests/test_recommendation_sessions.py` for session serialization, old/unknown field
    tolerance, track subset validation, and playlist result updates.
  - Extend `tests/test_playlists_api.py` for unknown session, non-recommended track, valid subset,
    idempotent replay, and Spotify add failure.
  - Extend `tests/test_feedback_api.py` for unknown session, non-recommended track, and valid event.
- Integration tests:
  - Extend `tests/test_recommendations_api.py` or add service-level tests proving
    `DemoApiService.recommend()` persists the recommendation session.
  - Add a full service flow test with local temp stores: recommend -> create playlist from returned
    track ID -> record feedback for the same track.
- UI/E2E scenarios:
  - None. This remains API-only.
- Regression scenarios:
  - Existing recommendation endpoint still works with deterministic intent parsing and no live
    OpenAI call.
  - Existing playlist idempotency still prevents duplicate Spotify playlists.
  - Existing feedback persistence still writes JSON events after validation.
  - Tests still avoid live Spotify, OpenAI, and AWS calls.

## Validation Commands

```bash
uv run pytest tests/test_recommendation_sessions.py tests/test_recommendations_api.py tests/test_playlists_api.py tests/test_feedback_api.py
uv run ruff format --check src tests
uv run ruff check src tests
uv run mypy src tests
uv run pytest
```

Manual local validation after implementation:

```bash
RECOMMENDER_CATALOG_RUN_ID=smoke-reccobeats-parquet \
RECOMMENDER_DATA_ROOT=data/local \
RECOMMENDER_DATA_MODE=local \
uv run music-recommender-api --host 127.0.0.1 --port 8000

bash scripts/demo_recommend.sh

SESSION_ID=<session-id-from-response> \
TRACK_IDS_JSON='["track-id-from-response"]' \
bash scripts/demo_create_playlist.sh
```

## Risks And Rollback

- Risk: Session persistence failure blocks recommendations that used to work.
  Mitigation: Keep the JSON store simple, deterministic, and well-tested before wiring into the API.
  Rollback: Temporarily disable playlist validation and return to recommendation-only behavior.

- Risk: Playlist validation rejects legitimate user-selected tracks from another recommendation.
  Mitigation: Validate against the exact `session_id` the caller supplies and return clear error
  messages listing invalid track IDs.
  Rollback: Allow all track IDs only in local development behind an explicit environment flag, if
  absolutely necessary.

- Risk: JSON stores are not safe for concurrent writes.
  Mitigation: Accept this for local class-demo usage; document that DynamoDB is required for AWS
  multi-request durability.
  Rollback: Keep local stores for demos and avoid concurrent local load testing.

- Risk: Session payloads become too large if full recommendation payloads are stored.
  Mitigation: Store compact track metadata and score fields, not full catalog rows or Spotify raw
  payloads.
  Rollback: Store only IDs and playlist candidate fields, then load details from catalog when
  needed.

- Risk: DynamoDB adapter scope creeps into this first change.
  Mitigation: Use a protocol and JSON implementation first; make DynamoDB a separate plan/task.
  Rollback: Remove adapter scaffolding and keep only JSON stores.

## Handoff Notes

- Start with tests for rejected playlist creation before adding session persistence.
- Do not store secrets or raw OAuth payloads in session records.
- Keep public request models stable unless a test proves a new field is required.
- Prefer application-service validation in `DemoApiService` over adding Spotify-specific logic to
  `PlaylistService`.
- After this plan is implemented, the next strong milestone is a DynamoDB-backed implementation of
  the same session/feedback/playlist store protocols for AWS Lambda.
