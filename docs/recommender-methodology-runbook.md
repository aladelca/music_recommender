# Recommender Scientific Methodology Runbook

This runbook specifies the implemented Outside the Loop recommender, its evidence rules, and the
five-user evaluation protocol. The production ranker is deterministic and versioned as
`explicit-discovery-v1`. It is not a trained machine-learning model and its weights are engineering
hypotheses, not established causal effects.

## Product Claim

Outside the Loop tests whether explicit user seeds plus transparent, independent discovery evidence
can produce recommendations that a small beta group prefers to their usual Spotify discovery
experience. It does not claim broad superiority or statistical significance.

Spotify is not a ranking input. The product does not use Spotify saved tracks, top items, listening
history, existing playlists, popularity, audio features, or collaborative/profile vectors. Spotify
is used only for account identity, post-ranking exact track mapping/display, attributed playback
links, and a user-confirmed playlist write.

## Inputs And Unit Of Analysis

The ranked unit is a MusicBrainz recording MBID. Inputs are:

- One to five MusicBrainz artist/recording seeds explicitly selected by the current account.
- A user-authored prompt of 2-500 characters.
- `familiar`, `balanced`, or `adventurous` control.
- Explicit-content permission.
- First-party blocked artist/recording MBIDs from that account's feedback.
- Fresh normalized MusicBrainz and ListenBrainz facts stored in Supabase.

No user ID, Spotify profile, external catalog run, local path, S3 URI, CSV, or Parquet file is
accepted by the product recommendation request.

## Automated Candidate Construction

1. MusicBrainz search resolves explicit artist/recording text to canonical MBIDs.
2. For recording seeds, canonical artist-credit MBIDs provide artist expansion roots.
3. ListenBrainz Core artist-radio and tag-radio endpoints return candidate recording MBIDs and
   source facts.
4. ListenBrainz recording metadata supplies bounded title, artist credit, release, tag, ISRC, and
   listener fields when available.
5. Normalized entities and edges retain source adapter, algorithm version, fetch time, expiry,
   strength/listener values, and bounded source facts.
6. Duplicate edges are merged by deterministic source/seed/recording ordering.

Positive source caches generally expire after seven days; negative results expire after one hour;
normalized entities can remain fresh for 30 days. The distributed rate limiter enforces the
MusicBrainz/ListenBrainz call cadence across Lambda instances. Missing/stale data produces a queued,
degraded, insufficient, or failed state instead of a file fallback.

## Prompt Intent

The default `deterministic-intent-v1` parser normalizes only the user-authored prompt. It assigns a
label and small tag set for recognized categories such as high-energy, calm/focus, uplifting, or
balanced exploration. The request's adventure and explicit controls remain authoritative.

An optional future prompt-only model boundary may receive the normalized prompt string and must
return a strict label/tag schema. It may not receive account identity, seeds/history, Spotify data,
candidate records, feedback, or source payloads. No LLM orchestration chooses production tracks.

## Eligibility And Diversity

A candidate is excluded before scoring when:

- Its edge does not originate from a currently selected seed.
- The MusicBrainz recording entity is missing or stale.
- It is itself a selected seed.
- Its recording or any credited artist is blocked by this account.
- The source establishes it as explicit while explicit content is disabled.

After sorting, the production selector returns at most one recording per primary artist. Primary
artist identity is an MBID, not a normalized display name. This is a hard diversity constraint.

## Frozen Scoring Equation

For candidate `i`:

```text
score_i =
    0.35 * prompt_tag_fit_i
  + bridge_weight(adventure) * seed_bridge_strength_i
  + discovery_weight(adventure) * discovery_value_i
  + 0.15 * evidence_quality_i
```

Adventure weights are:

| Mode | Seed bridge | Discovery value |
| --- | ---: | ---: |
| Familiar | 0.40 | 0.10 |
| Balanced | 0.30 | 0.20 |
| Adventurous | 0.20 | 0.30 |

Each component and the total are clamped to `[0, 1]`.

### `prompt_tag_fit`

The component is the fraction of requested intent tags present in normalized entity/edge tags. If
the parser emits no tags, the neutral prior is `0.5`; unsupported tags contribute zero.

### `seed_bridge_strength`

The component uses the maximum source edge strength. If an edge has no numeric strength, a similar
artist edge contributes `0.6` and another supported edge contributes `0.5`. More than one distinct
source adapter adds `0.05` per extra adapter before clamping.

### `discovery_value`

When listener counts are present, the minimum supporting edge count is transformed as:

```text
popularity_proxy = log(1 + listener_count) / log(1 + 1,000,000)
discovery_value = 1 - clamp(popularity_proxy)
```

This deliberately gives more discovery weight to less-exposed candidates. It is not Spotify
popularity. If no listener count exists, the neutral value is `0.5` and the evidence card discloses
the missing support.

### `evidence_quality`

Auditable data completeness contributes:

| Available fact | Contribution |
| --- | ---: |
| Non-placeholder recording title | 0.25 |
| Artist credit | 0.20 |
| Tags | 0.15 |
| At least one source edge | 0.20 |
| Edge strength or listener count | 0.20 |

This rewards explainability rather than confidence in user satisfaction.

### Ordering

Candidates sort by descending total, then descending evidence quality, then ascending recording
MBID. The artist constraint is applied greedily in that order. Given the same database snapshot,
prompt, controls, preferences, parser/ranking versions, and code, output ordering is deterministic.

## Evidence Cards

`evidence-v1` permits only five reason kinds:

- `selected_seed`: the user's explicit seed MBID.
- `source_edge`: exact ListenBrainz adapter and algorithm version.
- `tag_match`: a requested tag actually present in source facts.
- `listener_support`: a reported listener count tied to an adapter.
- `source_diversity`: more than one distinct supported adapter.

Each reason has a fixed source and exact detail-key schema. Before persistence, validation checks it
against the ranked candidate. Missing tag/listener/artist/title/explicit information becomes a
structured limitation; unsupported prose cannot be stored as evidence. Evidence does not expose
the internal decimal total as confidence.

## Post-Ranking Spotify Mapping And Coverage

Only after independent ranking does the backend search Spotify for display/export IDs:

1. Exact ISRC match, when MusicBrainz/ListenBrainz supplied an ISRC.
2. Otherwise exact normalized recording title plus credited artist.
3. Unmapped, duplicate, or disallowed explicit Spotify results are removed without rescoring.

Spotify IDs, popularity, search order, and profile fields never affect `score_i`.

The result targets ten unique mapped tracks. Status is:

- `ready`: ten returnable tracks and at least 90% verifiable evidence coverage.
- `degraded`: ten tracks but evidence coverage below 90%.
- `insufficient`: fewer than ten returnable Spotify mappings.

The response exposes candidate/mapped/evidence counts and limitations so source coverage cannot be
mistaken for recommendation certainty.

## Feedback Effects

`hide_artist` and recording dislikes update only that account's blocked MBID preferences and affect
later eligibility. Likes, saves, skips, comments, playlist choices, and evaluation ratings are
stored for product analysis but do not silently retrain or reweight the frozen ranker. No tester's
feedback affects another tester.

## Reproducibility Record

For every evaluated session retain:

| Field | Record |
| --- | --- |
| Git commit and deployment ID | Git/Vercel/CloudFormation |
| Parser, ranking, evidence, and source-adapter versions | Recommendation snapshot |
| Seed IDs/MBIDs and controls | Account-owned session snapshot |
| Source fetch/expiry and edge facts | Supabase source snapshot |
| Prompt | Account-owned session only; never operational logs |
| Ordered recommendation/evidence output | Recommendation items |
| Mapping source and Spotify ID | Post-ranking mapping snapshot |
| Review/export outcome | Review and idempotent export records |

Do not export raw user sessions to local CSV/Parquet/S3. Aggregate beta analysis should query
Supabase through an approved backend/operator process and emit only non-identifying summaries.

## Five-Tester Evaluation Protocol

The first round freezes `explicit-discovery-v1`, `deterministic-intent-v1`, `evidence-v1`, and
`lb-core-v1`. Each of the five testers completes at least three sessions on separate prompts:

1. Comfort-zone discovery from explicit favorite-adjacent seeds.
2. A mood or activity request.
3. An intentionally adventurous request.

Rotate prompt-category order across testers to reduce order/fatigue effects. Before first use,
collect one baseline satisfaction question about normal discovery. After every session collect:

- Better, same, worse, or not sure versus usual Spotify discovery.
- Explanation usefulness, 1-5.
- Novelty quality, 1-5.
- Track selections/removals, feedback events, and whether a playlist was exported.
- Optional qualitative comment, kept account-scoped and out of logs.

A bug or behavior change starts a new version/round. Do not tune weights after looking at partial
round results.

## Decision Criteria And Analysis

The product hypothesis passes the exploratory beta when:

- At least four testers prefer Outside the Loop in a majority of their rated sessions.
- Median explanation usefulness is at least 4/5.
- Every tester accepts at least 20% of recommendations across the protocol.
- No unresolved evidence-accuracy, cross-account, policy, or wrong-playlist-owner defect remains.

With five testers, analysis is descriptive: report counts, medians, per-user ranges, source/evidence
coverage, selected-track rate, export rate, return sessions, cache hit rate, and p50/p95 generation
latency. Do not use null-hypothesis significance tests, population claims, or treat repeated sessions
from one user as independent people.

Useful diagnostic comparisons include component ablations, familiar versus adventurous settings,
source adapter coverage, and mapping/evidence failure categories. They explain behavior but do not
replace the user comparison outcome.

## Known Limitations

- Hand-selected weights are not calibrated from relevance judgments.
- ListenBrainz listener counts and radio results have participation/exposure bias.
- Less-listened does not necessarily mean novel to a particular tester.
- Tag quality and coverage vary by genre, language, region, and release.
- Spotify post-ranking mapping can fail or choose no result despite a valid MusicBrainz recording.
- Five Development Mode testers cannot establish market-wide superiority.
- Explicit status may remain unknown until post-ranking mapping.

Any methodology change must add deterministic tests, update the version, rerun source/evidence and
tenant-isolation tests, rebuild artifacts, and start a new frozen evaluation round.
