# Recommender Scientific Methodology Runbook

This runbook defines what the recommender currently computes, how to reproduce a result, and how to
evaluate changes without overstating evidence. The deployed recommender is a deterministic,
rule-based hybrid ranker with optional LLM intent parsing and orchestration. It is not a trained
machine-learning ranking model, and its weights have not yet been statistically calibrated.

## Methodological Claim

The implementation operationalizes three hypotheses:

1. Tracks closer to a prompt-derived mood target are more relevant.
2. Tracks connected to the user's Spotify behavior are more personally relevant.
3. A small novelty term and artist-diversity constraint improve list usefulness without overwhelming
   mood or taste.

These are testable product hypotheses, not validated scientific conclusions. Current constants are
engineering priors. General effectiveness must be established with offline and online evaluation.

## Inputs And Units Of Analysis

The unit ranked is a unique Spotify track ID. The candidate set is the union of:

- The selected S3 catalog run, enriched by its selected offline interaction run.
- Unique tracks captured during the latest live Spotify profile sync.

The cached user profile contains known track IDs, liked track IDs, liked artist names, and
continuous track/artist affinities. Request-level liked, known, and blocked values are merged into
that profile for one recommendation call.

Track features can include Spotify popularity, audio valence, energy, danceability, lyrics
sentiment, and an offline maximum implicit rating. Live profile-only candidates currently contain
identity, artists, explicit status, popularity, and Spotify URL; if they are absent from the offline
catalog, they have no audio, lyrics, or interaction features.

## Spotify Profile Construction

Profile signals are normalized to `[0, 1]`. When a track or artist appears in more than one source,
the maximum source weight is retained rather than summing repeated exposure.

| Spotify source | Track affinity | Artist affinity | Added to liked sets | Added to known tracks |
| --- | ---: | ---: | --- | --- |
| Saved track | `1.0` | `0.9` | Track and artists | Yes |
| Short-term top track | `0.9` | `0.9` | Track and artists | Yes |
| Medium-term top track | `0.8` | `0.8` | Track and artists | Yes |
| Long-term top track | `0.7` | `0.7` | Track and artists | Yes |
| Short/medium/long top artist | N/A | `0.9` / `0.8` / `0.7` | Artist | N/A |
| Explicitly selected playlist track | `0.6` | `0.6` | No | Yes |
| General playlist track | `0.4` | `0.4` | No | Yes |
| Recently played track | `0.3` | `0.3` | No | Yes |

Saved and top items are treated as stronger positive evidence. Playlist and recent-play signals are
treated as familiarity evidence because presence alone does not prove preference. Profile sync
deduplicates track candidates and records source counts, selected playlists, time ranges, sync time,
and missing optional scopes for auditability.

## Prompt To Mood Intent

Every request becomes a structured intent with label, target valence, target energy, target
danceability, explicit-content permission, blocked artists, and rationale.

The deterministic parser uses these mappings:

| Trigger language | Label | Valence | Energy | Danceability |
| --- | --- | ---: | ---: | ---: |
| `break up`, `breakup`, `broke up`, `cheer me up` | `cheer-up` | `0.88` | `0.78` | `0.76` |
| `party`, `dance`, `workout`, `hype` | `high-energy` | `0.78` | `0.90` | `0.86` |
| `calm`, `focus`, `study`, `relax` | `calm-focus` | `0.58` | `0.34` | `0.42` |
| No trigger | `balanced` | `0.65` | `0.62` | `0.62` |

The phrases `clean`, `no explicit`, or `family` disable explicit tracks. Text immediately following
`avoid `, through the next comma or period, becomes one blocked artist name.

With `use_openai_agent: true`, the default `gpt-5-nano` intent agent emits the same structured
fields and is instructed to keep targets between 0 and 1. A second agent orchestrates tools with a
six-turn limit. It must call the catalog ranker, and guardrails reject final track IDs that were not
returned by that tool. The LLM can alter the interpreted intent and choose/order a subset of ranked
IDs, but it cannot introduce tracks outside the candidate catalog.

## Eligibility Rules

Before scoring:

- Duplicate track IDs are removed, keeping the first catalog occurrence.
- Explicit tracks are removed when the intent disallows explicit content.
- Tracks matching a blocked artist from either prompt/request or profile are removed.

After scoring, no primary artist can contribute more than two selected tracks. These are hard
constraints and should have zero violations in evaluation.

## Scoring Model

For each eligible track `i`, the selection score is:

```text
score_i = clamp(
    0.65 * mood_i
  + 0.20 * taste_i
  + 0.05 * novelty_i
  + 0.10 * popularity_i
  - diversity_penalty_i,
  0,
  1
)
```

### Mood Fit

For each available audio feature `x` in valence, energy, and danceability:

```text
target_fit(x, target) = 1 - min(abs(clamp(x) - clamp(target)), 1)
```

The mood component is the arithmetic mean of all available values from:

- Valence target fit
- Energy target fit
- Danceability target fit
- Lyrics positive probability
- `1 - lyrics negative probability`

Missing components are omitted from the mean. A track with none of these features receives mood
fit `0.0`, not a neutral value. This materially disadvantages live profile-only tracks that have not
been enriched in the offline catalog.

### Taste Affinity

```text
taste_i = clamp(
    0.55 * any_liked_artist
  + 0.35 * liked_track
  + 0.35 * max_matching_artist_affinity
  + 0.40 * track_affinity
  + 0.20 * clamp(max_implicit_rating / 5),
  0,
  1
)
```

Artist comparison uses case-folded, accent-normalized names. Contributions can overlap and are
clamped to `1.0`. The offline implicit rating is not the feedback collected by the API; it comes
from the selected interaction dataset.

### Novelty And Popularity

`novelty_i` is `0.0` when the track is in the profile's known-track set and `1.0` otherwise.
`popularity_i` is Spotify popularity divided by 100 and clamped to `[0, 1]`; missing popularity is
`0.0`.

### Artist Diversity

Selection is greedy. At each position, remaining candidates are rescored with:

```text
diversity_penalty = min(0.15 * already_selected_from_primary_artist, 0.45)
```

The highest adjusted candidate is selected, and candidates from an artist already represented
twice are excluded. The returned score breakdown contains mood, taste, novelty, popularity,
diversity penalty, and total. Explanations are deterministic summaries of those computed signals;
they are not evidence that the track will cause a particular emotional outcome.

## Recommendation And Side-Effect Guardrails

- Recommendation IDs must come from the rank tool's candidate output.
- The API persists a recommendation session before accepting feedback or playlist creation.
- Feedback and playlist track IDs must belong to that session.
- `create_playlist: true` during recommendation creates only a candidate payload.
- `POST /playlists` is the explicit Spotify side effect and is idempotent by session ID.

These controls support traceability and prevent an agent or caller from inventing a Spotify track
or silently creating a playlist.

## Reproducing A Result

Record all of the following for each experimental run:

| Field | Source |
| --- | --- |
| Git commit | `git rev-parse HEAD` |
| Stack/template version | CloudFormation stack and commit |
| Catalog run ID | `CatalogRunId` stack parameter |
| Interaction run ID | `InteractionRunId` stack parameter |
| Profile version | `/profile` `synced_at`, source counts, and time ranges |
| Prompt and request additions | Recommendation request JSON |
| Intent path | `use_openai_agent` |
| Agent model | `OpenAIAgentModel` stack parameter or default |
| Output | Full recommendation response and `session_id` |

The deterministic path is reproducible for the same ordered catalog, profile snapshot, prompt,
request, and code version. Equal-score ties preserve input ordering, so catalog order is part of the
effective experiment state. The OpenAI path is not guaranteed to reproduce byte-identical intent or
ordering even with the same inputs.

Use [api-usage-runbook.md](api-usage-runbook.md) to capture the profile summary, request, and
response. Do not commit user profile payloads, access tokens, API keys, or private Spotify data as
test fixtures.

## Offline Evaluation Protocol

Before changing weights or profile-source rules:

1. Freeze code, catalog run, interaction run, profile snapshot, prompt set, and candidate ordering.
2. Define relevance from held-out first-party events such as like, save, accepted playlist add, and
   skip/dislike. Do not use the same event both as a ranking feature and evaluation label.
3. Split interactions chronologically so training or tuning never sees future behavior.
4. Compare the candidate change with the current production constants and simple baselines such as
   popularity-only, mood-only, and taste-only.
5. Report ranking quality, constraint compliance, coverage, diversity, and latency together.
6. Run ablations that remove audio, lyrics, Spotify profile, popularity, and each source family.
7. Preserve per-query outputs so regressions can be inspected, not just averaged.

Recommended ranking metrics are `NDCG@K`, `Recall@K`, `HitRate@K`, and mean reciprocal rank. Report
catalog coverage, novel-track rate, intra-list artist diversity, maximum artist concentration, and
mean mood-target distance. Explicit and blocked-artist violation counts must remain zero. Also
report p50/p95 API latency and dependency failure rate.

For a single user or small prompt set, report distributions and bootstrap confidence intervals or a
paired randomization/permutation analysis. Do not present a p-value from repeated recommendations
to one person as evidence of population-level improvement.

## Online Evaluation Protocol

When there is enough first-party traffic, compare one isolated change at a time. Pre-register the
primary outcome and stopping rule before examining results. Suitable outcomes include accepted
recommendation rate, like/save rate, skip/dislike rate, playlist creation rate, and retained tracks
after a fixed period.

Randomize prompt/order effects and use session-level assignment. Keep safety constraints identical
between variants. Analyze OpenAI intent parsing separately from score-weight changes so an observed
difference can be attributed to the correct component.

The current single-user deployment cannot support a population A/B test. It can support repeated
within-user usability trials, but conclusions are personal and exploratory.

## Current Limitations And Biases

- Ranking weights and source weights are hand-selected and not calibrated from outcomes.
- API feedback is persisted but does not update the profile, catalog, or ranker.
- The S3 seed catalog and profile sync limits determine which music can be discovered.
- Spotify popularity creates exposure bias toward already popular tracks.
- Missing audio or lyrics data lowers mood evidence; fully missing mood features score zero.
- Saved/top/playlist presence is an imperfect proxy for preference and can be stale or contextual.
- Lyrics sentiment is not equivalent to listener mood and may perform unevenly across languages,
  genres, irony, and instrumental music.
- Artist-name normalization can merge or miss ambiguous artist identities.
- One user's refresh token and behavior cannot justify claims about other users.
- Agent-based intent parsing introduces external-model drift and nondeterminism.

Future learned ranking should use consented first-party outcomes, chronological train/validation/test
splits, leakage checks, and a documented model/data version. It should not treat Spotify access
tokens, private profile payloads, or copyrighted content as training artifacts.

## Validation Gates

Run the existing implementation tests after a methodology-affecting change:

```bash
uv run pytest \
  tests/test_recommender_scoring.py \
  tests/test_profile_sync.py \
  tests/test_agent_intent.py \
  tests/test_agent_orchestrator.py \
  tests/test_recommendations_api.py
```

Then run the full quality suite and deployed smoke test before release:

```bash
uv run ruff format --check src tests
uv run ruff check src tests
uv run mypy src tests
uv run pytest

STACK_NAME=music-recommender-demo \
AWS_REGION_VALUE=us-east-1 \
bash scripts/smoke_test_deployed_api.sh
```
