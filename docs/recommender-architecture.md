# Natural Language Music Recommender Architecture

## Topic

Design direction for a music recommender where a user can describe what they want in natural
language, for example: "I just broke up with my girlfriend and I want songs to cheer me up."

The system should recommend Spotify-playable songs that fit the current mood and goal while taking
into account the user's existing taste.

## Objective

Build a recommender that feels conversational at the entry point but remains deterministic,
inspectable, and testable in the recommendation engine.

The target experience is:

1. The user authenticates with Spotify.
2. The app learns from consented user signals such as saved tracks, top artists, top tracks,
   recent plays, and app-specific feedback.
3. The user enters a natural-language request.
4. The system converts that request into a structured music intent.
5. The recommender returns tracks with short, grounded explanations and refinement controls.
6. The user can save the result as a Spotify playlist or ask for adjustments.

## Current Repo Fit

This repository already has the foundation for an offline data and feature pipeline:

- Spotify catalog extraction in `src/music_recommender/sources/spotify.py`.
- ReccoBeats audio feature ingestion in `src/music_recommender/sources/reccobeats.py`.
- Lyrics ingestion through LRCLIB and lyrics.ovh.
- Lyrics language and sentiment enrichment in `src/music_recommender/nlp/`.
- ListenBrainz public listen data ingestion in `src/music_recommender/pipeline/network.py`.
- Local and S3 medallion storage for bronze, silver, and gold datasets.

The missing product layer is the online recommendation system:

- Spotify user OAuth.
- User profile sync.
- Natural-language intent parsing.
- Candidate generation.
- Ranking and diversification.
- Feedback capture.
- API and UI.

## Spotify Constraints

As of 2026-07-02, the architecture should not depend on Spotify's own recommendation or audio
analysis capabilities as the core recommender intelligence.

Key constraints:

- `GET /recommendations` is marked deprecated in the Spotify Web API reference.
- Spotify audio feature endpoints are also marked deprecated.
- Spotify states that Spotify Platform data and Spotify Content may not be used to train an AI or
  machine-learning model.
- User-specific endpoints require OAuth and consented scopes such as `user-top-read` and
  `user-library-read`.
- Spotify development mode and quota rules can constrain beta testing and public launch.

Practical implication: use Spotify primarily for authentication, user-consented signals, catalog
lookup, availability, playback links, and playlist creation. The recommender's model and scoring
logic should be built on first-party app feedback, open datasets, non-Spotify feature sources, and
transparent rules.

## Should It Be Agent Powered?

Use an agent or LLM for interpretation and orchestration, not as the recommender itself.

Good uses for an agent:

- Parse natural-language prompts into structured music intent.
- Ask a clarification question when the prompt is too vague.
- Choose safe tool calls such as "create playlist", "refine results", or "exclude this artist".
- Generate short explanations from known metadata and scores.

Avoid:

- Letting the LLM directly invent song lists.
- Training a model on Spotify content.
- Depending on Spotify's deprecated recommendation endpoint.
- Hiding ranking behavior behind an opaque agent loop.

The best split is:

- LLM layer: understands the user's situation and translates it into constraints.
- Recommender layer: retrieves, scores, filters, and diversifies songs.
- Tool layer: syncs Spotify data, creates playlists, and records feedback.

## Intent Model

The natural-language prompt should become a structured object before recommendation.

Example prompt:

> I just broke up with my girlfriend and I want songs to cheer me up.

Example intent:

```json
{
  "situation": "breakup",
  "goal": "cheer_up",
  "mood": {
    "desired_valence": "high",
    "desired_energy": "medium_high",
    "allow_catharsis": true,
    "avoid_too_sad": true
  },
  "taste": {
    "familiarity_bias": "medium",
    "discovery_level": "some"
  },
  "constraints": {
    "explicit_allowed": null,
    "language": null,
    "market": "user_market"
  }
}
```

The recommender should operate on this structured intent, not on raw prompt text.

## Recommendation Strategy

Use a hybrid recommender with several candidate sources.

Candidate sources:

- User taste candidates from saved tracks, top tracks, top artists, playlists, and recent plays.
- Similar catalog candidates from the repo's extracted artist and track catalog.
- Mood candidates from ReccoBeats audio features such as valence, energy, danceability, tempo, and
  acousticness.
- Lyrics candidates from sentiment, language, and eventually lyric embeddings where licensing
  allows.
- Collaborative candidates from ListenBrainz interactions, especially for open educational training.
- Spotify search/catalog lookups for availability and display metadata.

Ranking score:

```text
score =
  mood_fit
  + taste_affinity
  + collaborative_signal
  + novelty_bonus
  + quality_or_popularity_prior
  + diversity_adjustment
  - blocked_artist_penalty
  - repetition_penalty
```

The first version can be rule-based and transparent. A later version can learn weights from
first-party app feedback such as likes, skips, saves, refinements, and playlist exports.

## Proposed Architecture

### Offline Data Layer

Keep the existing extraction pipeline and extend it into feature generation:

- `bronze`: raw source snapshots.
- `silver`: normalized artists, tracks, albums, lyrics, audio features, and user listens.
- `gold`: recommender-ready tables such as track features, user-track interactions, artist affinity,
  mood clusters, and candidate pools.

Recommended additions:

- `gold/track_features`: one row per track with normalized audio, lyric, catalog, and popularity
  features.
- `gold/user_profiles`: app-owned user taste vectors and explicit feedback summaries.
- `gold/candidate_sets`: precomputed nearest-neighbor or mood-based retrieval groups.

### Online Backend

Add an API service that serves the product experience.

Suggested modules:

- `auth`: Spotify OAuth and token refresh.
- `profiles`: sync and normalize user taste signals.
- `intent`: LLM-backed prompt-to-intent parser with schema validation.
- `retrieval`: candidate generation from catalog, features, and user profile.
- `ranking`: scoring, filtering, and diversification.
- `feedback`: app-specific events and preference updates.
- `playlists`: Spotify playlist creation and update tools.

FastAPI is a practical fit for the current Python repo, but the key decision is keeping the
recommendation logic in ordinary Python modules that can be tested without the web server.

### Storage

Use different storage for different latency needs:

- S3 or local Parquet for offline snapshots and experiments.
- Postgres for app users, OAuth token metadata, feedback, and recommendation sessions.
- pgvector or Qdrant for vector retrieval if embeddings are added.
- Redis only if caching or background job coordination becomes necessary.

### Background Jobs

Use background jobs for:

- Spotify profile sync.
- Catalog refresh.
- Feature generation.
- Candidate precomputation.
- Feedback aggregation.

The API request path should stay fast: parse intent, load profile, retrieve candidates, rank,
return results.

## User Experience Ideas

Core first screen:

- A single natural-language input.
- Spotify connect status.
- A result list with album art, song, artist, reason, and quick actions.
- Refinement chips such as "more upbeat", "less sad", "more familiar", "more discovery",
  "Spanish only", "no explicit", and "save playlist".

Recommendation response should show:

- Track title and artist.
- Spotify link or playable embed.
- Why it was chosen.
- Confidence or fit tags such as "upbeat", "familiar", "new discovery", or "cathartic".

The best UX pattern is iterative:

1. User gives an emotional request.
2. App returns a coherent set.
3. User adjusts with natural language or controls.
4. App records feedback and improves the next set.

## MVP Roadmap

1. Define `MoodIntent` and `RecommendationRequest` schemas.
2. Build a local recommender that reads existing Parquet data and returns ranked tracks for a prompt.
3. Add deterministic rule-based scoring for mood fit and user taste.
4. Add an LLM intent parser with strict JSON schema validation and fallback defaults.
5. Add Spotify OAuth and user profile sync.
6. Add feedback events: like, dislike, hide artist, save, skip, and refine.
7. Add playlist creation once recommendations are useful.
8. Add vector retrieval and learned ranking only after enough first-party feedback exists.

## Open Decisions

- Is this a personal/demo app, a class project, a private beta, or a public product?
- Should the MVP require Spotify login from day one, or support manual seed artists/tracks first?
- Is the main success criterion mood accuracy, music discovery, or "sounds like my taste"?
- How much explanation should the UI show without making the product feel analytical?
- What policy review is needed before storing or deriving features from Spotify user data?

## Recommendation

Start with a hybrid, transparent recommender:

- Use an LLM only to parse intent and generate grounded explanations.
- Use rules and feature scoring for the first ranking engine.
- Use ReccoBeats, lyrics NLP, ListenBrainz, and first-party app feedback as the recommender
  intelligence.
- Use Spotify for user consent, user signals, catalog lookup, playback links, and playlist creation.

This path fits the existing repo and avoids relying on deprecated Spotify recommendation/audio
feature endpoints.

## Sources

- [Spotify Web API: Get Recommendations](https://developer.spotify.com/documentation/web-api/reference/get-recommendations)
- [Spotify Web API: Get Track's Audio Features](https://developer.spotify.com/documentation/web-api/reference/get-audio-features)
- [Spotify Web API: Get User's Top Items](https://developer.spotify.com/documentation/web-api/reference/get-users-top-artists-and-tracks)
- [Spotify Web API: Get User's Saved Tracks](https://developer.spotify.com/documentation/web-api/reference/get-users-saved-tracks)
- [Spotify Web API: Authorization](https://developer.spotify.com/documentation/web-api/concepts/authorization)
- [Spotify Web API: Quota Modes](https://developer.spotify.com/documentation/web-api/concepts/quota-modes)
- [Spotify Developer Policy](https://developer.spotify.com/policy)
