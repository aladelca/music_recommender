# Recommender Science And Architecture Reference

This document specifies how the production Outside the Loop recommender constructs, ranks,
explains, evaluates, and exports recommendations. It combines the computational architecture with
the scientific protocol used for the five-tester beta.

The production ranker is a deterministic, versioned heuristic. It is not a trained machine-learning
model, and its weights are hypotheses to evaluate rather than empirically calibrated causal effects.
Spotify is not a ranking input.

## Research Question And Product Claim

The beta asks:

> Can explicit user-selected music seeds plus transparent, independent discovery evidence produce
> sessions that a small group of testers prefers to its usual Spotify discovery experience?

This is an exploratory product question. Five testers cannot establish population-level superiority,
market fit, or statistical significance. The result is useful for deciding whether the product
mechanism deserves a larger evaluation.

The product claim is deliberately narrow:

- The user controls one to five artist or recording seeds and the session prompt.
- MusicBrainz provides canonical identity and ListenBrainz provides candidate discovery facts.
- A frozen deterministic equation orders eligible candidates.
- Every displayed reason must be supported by stored source facts.
- Spotify is used only for identity, post-ranking mapping/attribution, and an explicit playlist write.
- The user reviews the exact tracks, order, name, and visibility before export.

## Computational Architecture

```text
Explicit user seeds
  -> MusicBrainz canonical MBIDs
       -> asynchronous ListenBrainz expansion
            -> normalized entities and candidate edges in Supabase

Prompt + adventure + explicit control + owned seeds/preferences
  -> deterministic intent parser
  -> eligibility filters
  -> explicit-discovery-v1 score
  -> deterministic sort and artist diversity
  -> evidence-v1 validation
  -> Spotify post-ranking mapping
  -> coverage gate and immutable recommendation snapshot
  -> user review and order
  -> idempotent Spotify playlist export
  -> account-scoped feedback and evaluation
```

Online responsibilities are split across two AWS Lambdas:

- The product API validates account ownership, parses intent, ranks cached discovery facts, maps
  ranked candidates to Spotify, snapshots results, and handles review/export.
- The SQS discovery worker expands seeds through ListenBrainz, normalizes source payloads, and writes
  cache/entity/edge records. It does not select final tracks.

Supabase is the only product persistence layer. No local path, S3 URI, CSV, Parquet file, external
catalog run ID, or caller-selected user ID is accepted by the recommendation API.

## Units, Inputs, And Outputs

### Ranked Unit

The unit ranked by the model is a MusicBrainz recording MBID. This is independent of a Spotify track
ID and can represent a recording before a market-specific Spotify mapping is available.

### First-Party Inputs

- One to five explicitly confirmed MusicBrainz artist or recording seeds.
- A 2-500 character user-authored prompt.
- `familiar`, `balanced`, or `adventurous` exploration mode.
- Explicit-content permission.
- The current account's blocked recording and artist MBIDs.

### Independent Source Inputs

- MusicBrainz canonical artist/recording identity, artist credits, releases, tags, and ISRCs.
- ListenBrainz artist-radio and tag-radio candidate edges.
- ListenBrainz edge strengths, tags, recording metadata, and listener counts when available.
- Source adapter/algorithm version, fetch time, expiry, and bounded source facts.

### Explicitly Excluded Inputs

The product does not read or score Spotify top items, saved tracks, recent plays, playlists,
popularity, audio features, recommendation endpoints, or profile-derived taste vectors. It does not
use feedback from another account. It does not use ReccoBeats or the repository's legacy extracted
datasets.

## Frozen Version Set

| Concern | Production version |
| --- | --- |
| Prompt parsing | `deterministic-intent-v1` |
| Candidate adapters | `lb-core-v1` |
| Ranking | `explicit-discovery-v1` |
| Evidence schema | `evidence-v1` |

The version set is frozen for one evaluation round. A behavior or weight change requires a new
version and a new round; silently changing implementation under an existing version would invalidate
comparisons.

## Recommendation Pipeline

### 1. Canonical Seed Selection

The user searches MusicBrainz for artists or recordings and confirms stable MBIDs. Search results do
not become seeds automatically. The service stores the selected entity type, MBID, display label,
source, position, and timestamp under the authenticated account.

Recording seeds use their MusicBrainz artist credits as expansion roots. Artist seeds are already
expansion roots. The database enforces one to five active seeds per account.

### 2. Candidate Construction

`POST /discovery/jobs` fingerprints the current seed set and enqueues one FIFO job. The worker:

1. Claims the account/job lease idempotently.
2. Loads fresh cached data where available.
3. Calls ListenBrainz artist radio for each seed artist.
4. Calls ListenBrainz tag radio for up to three tags found on selected seed entities.
5. Deduplicates and bounds expansion to 100 candidate recording MBIDs.
6. Fetches normalized recording metadata in batches.
7. Stores candidate edges keyed by seed, candidate, adapter, and algorithm version.

The worker records source degradation rather than inventing candidates. A source-wide transient
failure is retried at most three times through SQS; exhausted work reaches the dead-letter queue.

### 3. Cache And Rate-Limit Semantics

| Record | Positive freshness | Negative freshness |
| --- | ---: | ---: |
| MusicBrainz search/entity resolution | Up to 30 days | 1 hour |
| ListenBrainz candidate expansion | 7 days | 1 hour |
| Normalized recording entity | 30 days | Not applicable |
| Spotify export mapping | At most 24 hours | Not persisted |

A distributed database reservation prevents concurrent Lambda instances from violating the source
call cadence. Expired records are not treated as fresh, and a source outage never falls back to a
file or S3 dataset.

### 4. Prompt Intent

`deterministic-intent-v1` normalizes only the current prompt. It maps bounded recognized language to
a small mood/activity tag set and label. The explicit request fields for adventure and explicit
content remain authoritative.

The current deployment does not use an LLM to choose tracks. Any future prompt-only model may
receive the prompt and return a strict intent schema, but it may not receive account identity,
Spotify data, seeds/history, candidates, feedback, or source payloads.

### 5. Eligibility

A candidate is excluded before scoring when:

- No edge connects it to a currently selected seed.
- Its normalized MusicBrainz recording entity is missing.
- It is one of the selected seed recordings.
- Its recording MBID is blocked by this account.
- Any credited artist MBID is blocked by this account.
- Its source data establishes `explicit=true` while explicit content is disabled.

Unknown explicit status is disclosed and checked again after Spotify mapping. Unknown is not treated
as known-safe evidence.

### 6. Frozen Ranking Equation

For eligible candidate `i`:

```text
score_i =
    0.35 * prompt_tag_fit_i
  + bridge_weight(adventure) * seed_bridge_strength_i
  + discovery_weight(adventure) * discovery_value_i
  + 0.15 * evidence_quality_i
```

Adventure changes only the bridge/discovery tradeoff:

| Mode | Bridge weight | Discovery weight |
| --- | ---: | ---: |
| Familiar | 0.40 | 0.10 |
| Balanced | 0.30 | 0.20 |
| Adventurous | 0.20 | 0.30 |

All components and the final score are clamped to `[0, 1]`.

#### `prompt_tag_fit`

This is the fraction of requested intent tags found in normalized entity or edge tags. When the
parser emits no tags, the component uses a neutral prior of `0.5`. Unsupported tags contribute zero.

#### `seed_bridge_strength`

This uses the maximum numeric edge strength. A similar-artist edge without numeric strength uses
`0.6`; another supported edge without strength uses `0.5`. Each distinct additional source adapter
adds `0.05`, then the result is clamped.

#### `discovery_value`

When listener support exists, the smallest supporting edge count is transformed as:

```text
popularity_proxy = log(1 + listener_count) / log(1 + 1,000,000)
discovery_value = 1 - clamp(popularity_proxy)
```

This favors less-exposed candidates within the independent source. It is not a personalized novelty
estimate and is not Spotify popularity. Missing listener support receives a neutral `0.5` plus an
evidence limitation.

#### `evidence_quality`

This measures auditable data completeness, not predicted satisfaction:

| Available source fact | Contribution |
| --- | ---: |
| Non-placeholder recording title | 0.25 |
| Artist credit | 0.20 |
| Tags | 0.15 |
| At least one candidate edge | 0.20 |
| Edge strength or listener count | 0.20 |

### 7. Ordering And Diversity

Candidates sort by descending total score, then descending evidence quality, then ascending
recording MBID. Selection greedily permits at most one recording per primary artist MBID. Given the
same source snapshot, seed set, prompt, controls, preferences, code, and versions, the result is
deterministic.

The internal decimal score is not presented as confidence or probability. It is an ordering value
for this heuristic.

### 8. Evidence Construction

`evidence-v1` permits only source-backed reason kinds:

| Kind | Source | Required fact |
| --- | --- | --- |
| `selected_seed` | First party | A seed MBID on a candidate edge |
| `source_edge` | ListenBrainz | Seed, adapter, and algorithm version tuple |
| `tag_match` | ListenBrainz | Requested tag present in source facts |
| `listener_support` | ListenBrainz | Listener count and adapter tuple |
| `source_diversity` | ListenBrainz | More than one distinct adapter |

Evidence validation checks exact detail keys and verifies every reason against the ranked candidate
before persistence. Missing tags, listener support, artist credit, title, or explicit status become
structured limitations. Free-form generated claims cannot enter an evidence card.

### 9. Spotify Post-Ranking Mapping

Only after independent ordering does the backend map candidates for display and export:

1. Exact ISRC match where an independent source supplied an ISRC.
2. Otherwise, exact normalized recording title plus credited artist.
3. Reject duplicate, mismatched, unmapped, or disallowed explicit results.

Spotify IDs, search order, popularity, and profile fields never change `score_i` or the relative
independent ranking. Removing an unmapped item does not trigger rescoring. Mapping is bounded to 20
uncached candidates, 20 search requests, and 12 elapsed seconds.

The target is ten unique mapped tracks. Coverage status is:

| Status | Rule |
| --- | --- |
| `ready` | Ten returnable tracks and at least 90% verifiable evidence coverage. |
| `degraded` | Ten tracks but evidence coverage below 90%. |
| `insufficient` | Fewer than ten returnable Spotify mappings. |

The session snapshot exposes candidate, mapped, and evidence counts. Coverage measures pipeline
completeness, not recommendation correctness.

### 10. Review, Export, And Feedback

Generation is read-only with respect to Spotify. The user selects and orders one to ten items and
freezes the playlist name and visibility. Export verifies that the payload exactly matches review,
then uses an idempotency record to create `/me/playlists` and append `/items` in the authenticated
Spotify account. Partial progress can resume without creating a duplicate playlist.

`hide_artist` and recording dislikes update only that account's eligibility preferences. Likes,
saves, skips, playlist choices, comments, and ratings are retained for analysis but do not silently
retrain or reweight the frozen ranker. One tester's data never affects another tester.

## Scientific Evaluation Methodology

### Hypotheses

The primary product hypothesis is directional:

```text
Most testers will prefer Outside the Loop in a majority of their rated sessions
over their usual Spotify discovery experience.
```

Secondary hypotheses are that explanations are useful, recommended tracks are novel enough to be
selected, and the review/export flow produces playlists users actually keep.

### Study Design

The initial round uses five testers. Each tester completes at least three sessions with the frozen
version set:

1. A familiar or favorite-adjacent seed session.
2. A mood or activity session.
3. An intentionally adventurous session.

Prompt-category order should rotate across testers to reduce order and fatigue effects. Before the
first session, record one baseline question about satisfaction with normal discovery. Do not expose
partial aggregate results or tune weights during the round.

### Measurements

After each session, collect:

- `better`, `same`, `worse`, or `not_sure` versus usual Spotify discovery.
- Explanation usefulness from 1 to 5.
- Novelty quality from 1 to 5.
- Selected-track count and rate.
- Whether review completed and a playlist was exported.
- Item feedback and an optional account-scoped qualitative comment.

Operational diagnostics include source/evidence coverage, mapping failures, cache hit rate, queue
age, generation latency, export failures, reconnects, and return sessions. Operational metrics are
not substitutes for user outcomes.

### Decision Criteria

The exploratory mechanism passes its first gate when all of the following hold:

- At least four testers prefer Outside the Loop in a majority of their rated sessions.
- Median explanation usefulness is at least 4/5.
- Every tester accepts at least 20% of recommendations across the protocol.
- No unresolved evidence-accuracy, cross-account, policy, or wrong-playlist-owner defect remains.

These are product decision thresholds, not inferential statistical thresholds.

### Analysis

Analysis is descriptive. Report tester and session counts, medians, per-user ranges, selected-track
rate, export rate, source/evidence coverage, and p50/p95 latency. Aggregate repeated sessions first
at the tester level where making tester-level claims; do not treat sessions from one person as
independent people.

Do not run null-hypothesis significance tests, publish population confidence claims, or present five
testers as evidence of broad superiority. Component ablations and familiar-versus-adventurous
comparisons can diagnose behavior, but they do not replace the primary user outcome.

## Reproducibility And Audit Record

Every evaluated session must retain:

| Record | Location or snapshot |
| --- | --- |
| Git commit and deployment identifiers | Release record |
| Parser, adapter, ranking, and evidence versions | Recommendation session |
| Prompt, controls, seeds, and preferences | Account-owned session snapshot |
| Source adapters, fetch/expiry times, edges, and facts | Source snapshot/cache tables |
| Ordered scores and evidence | Recommendation items |
| Spotify mapping source and track ID | Post-ranking mapping snapshot |
| Review order, name, and visibility | Session review state |
| Idempotent export result | Playlist export record |
| Feedback and comparison ratings | Account-owned outcome tables |

Prompts and comments are not operational log fields. Raw sessions are not exported to local files,
CSV, Parquet, or S3. Approved operator analysis should query Supabase and emit non-identifying
aggregates.

## Validity Limits And Biases

- Hand-selected weights are not calibrated against labeled relevance judgments.
- ListenBrainz participation and radio algorithms create exposure and community bias.
- Listener count is an imperfect proxy for exposure and not novelty for a specific person.
- Tag, artist-credit, ISRC, and explicit-status coverage vary by genre, language, market, and era.
- Spotify search can fail to map a valid recording or can expose multiple release variants.
- Hard one-track-per-artist diversity may remove relevant tracks and is not personalized.
- Explicit prompts and seeds may create expectancy effects in subjective ratings.
- Testers are a convenience sample and are not blinded to the product.
- Three sessions per tester are sensitive to novelty, fatigue, and transient source conditions.
- Five Development Mode users cannot establish generalizable preference or market demand.

These limitations should be included with any result summary. Evidence cards improve auditability;
they do not prove that a recommendation is good.

## Change Control

A change to candidate sources, parser behavior, eligibility, weights, tie-breaking, diversity,
evidence rules, Spotify mapping, or feedback effects must:

1. Add or update deterministic unit tests.
2. Increment the affected version identifier.
3. Run source, evidence, repository, and account-isolation tests.
4. Rebuild and verify deployment artifacts.
5. Start a new evaluation round rather than mixing results.

## Implementation And Test Map

| Concern | Primary implementation | Representative tests |
| --- | --- | --- |
| Intent parsing | `agents/intent.py` | `tests/test_product_intent.py` |
| Discovery job/worker | `product/discovery_service.py` | `tests/test_discovery_service.py` |
| ListenBrainz adapter | `sources/listenbrainz_api.py` | `tests/test_listenbrainz_api.py` |
| Scoring/diversity | `recommender/scoring.py` | `tests/test_discovery_ranking.py` |
| Evidence validation | `recommender/evidence.py` | `tests/test_recommendation_evidence.py` |
| Recommendation snapshot/mapping | `product/recommendation_service.py` | `tests/test_recommendation_service.py` |
| Review/export idempotency | `product/playlist_export_service.py` | `tests/test_playlist_export_service.py` |
| Feedback/evaluation | `product/feedback_service.py` | `tests/test_feedback_evaluation_service.py` |
| Tenant persistence | `storage/postgres_repositories.py` | `tests/integration/test_postgres_repositories.py` |

## Related Documents And Sources

- [`recommender-methodology-runbook.md`](recommender-methodology-runbook.md): concise frozen-method
  operating protocol.
- [`recommender-architecture.md`](recommender-architecture.md): source and online-pipeline overview.
- [`spotify-policy-assessment.md`](spotify-policy-assessment.md): Spotify data-use boundary.
- [`product-beta-acceptance.md`](product-beta-acceptance.md): owner and tester acceptance checklist.
- [MusicBrainz Web Service](https://musicbrainz.org/doc/Development/XML_Web_Service/Version_2)
- [ListenBrainz API](https://listenbrainz.readthedocs.io/en/latest/users/api/index.html)
- [Spotify Developer Policy](https://developer.spotify.com/policy)
