import { z } from "zod";

export const productUserSchema = z.object({
  display_name: z.string().nullable(),
  access_status: z.enum(["pending", "approved", "revoked"]),
  seed_ready: z.boolean(),
  reauthorization_required: z.boolean(),
});

export const seedSchema = z.object({
  id: z.string().uuid(),
  entity_type: z.enum(["artist", "recording"]),
  mbid: z.string().uuid(),
  display_name: z.string(),
  position: z.number().int().positive(),
  source: z.literal("musicbrainz"),
  selected_at: z.string(),
});

export const seedsResponseSchema = z.object({ seeds: z.array(seedSchema).max(5) });

export const musicSearchResultSchema = z.object({
  mbid: z.string().uuid(),
  entity_type: z.enum(["artist", "recording"]),
  name: z.string(),
  artist_credit: z.array(z.record(z.string(), z.unknown())),
  release_data: z.record(z.string(), z.unknown()),
  isrcs: z.array(z.string()),
  source: z.literal("musicbrainz"),
});

export const musicSearchResponseSchema = z.object({
  results: z.array(musicSearchResultSchema),
  source: z.literal("musicbrainz"),
  cached: z.boolean(),
});

export const discoveryJobSchema = z.object({
  id: z.string(),
  status: z.enum(["queued", "running", "ready", "degraded", "failed"]),
  source_adapters: z.array(z.string()),
  attempt_count: z.number().int().nonnegative(),
  error_code: z.string().nullable(),
  queued_at: z.string(),
  started_at: z.string().nullable(),
  completed_at: z.string().nullable(),
});

export const evidenceReasonSchema = z.object({
  kind: z.string(),
  source: z.enum(["first_party", "listenbrainz"]),
  text: z.string(),
  details: z.record(z.string(), z.unknown()),
});

export const evidenceSchema = z.object({
  recording_mbid: z.string().uuid(),
  evidence_version: z.string(),
  verifiable: z.boolean(),
  reasons: z.array(evidenceReasonSchema),
  limitations: z.array(z.string()),
});

export const recommendationItemSchema = z.object({
  recording_mbid: z.string().uuid(),
  original_rank: z.number().int().positive(),
  display: z.object({
    spotify_track_id: z.string(),
    name: z.string(),
    artist_names: z.array(z.string()),
    explicit: z.boolean(),
    spotify_url: z.string().url(),
  }),
  evidence: evidenceSchema,
  selected: z.boolean(),
  reviewed_order: z.number().int().positive().nullable(),
});

export const recommendationSessionSchema = z.object({
  id: z.string().uuid(),
  status: z.enum([
    "queued",
    "ready",
    "degraded",
    "insufficient",
    "reviewed",
    "exported",
    "failed",
  ]),
  prompt: z.string(),
  controls: z.record(z.string(), z.unknown()),
  intent: z.record(z.string(), z.unknown()),
  seed_ids: z.array(z.string().uuid()),
  source_coverage: z.record(z.string(), z.unknown()),
  ranking_version: z.string(),
  generated_at: z.string(),
  updated_at: z.string(),
  review: z.object({
    playlist_name: z.string().nullable(),
    public: z.boolean().nullable(),
  }),
  recommendations: z.array(recommendationItemSchema),
});

export const historySchema = z.object({
  sessions: z.array(
    z.object({
      id: z.string().uuid(),
      status: z.string(),
      prompt: z.string(),
      ranking_version: z.string(),
      generated_at: z.string(),
    }),
  ),
  next_cursor: z.string().nullable(),
});

export const playlistExportSchema = z.object({
  id: z.string().uuid(),
  session_id: z.string().uuid(),
  status: z.string(),
  spotify_playlist_id: z.string().nullable(),
  spotify_playlist_url: z.string().url().nullable(),
  name: z.string(),
  public: z.boolean(),
  tracks_added: z.number().int().nonnegative(),
  track_count: z.number().int().positive(),
  idempotent_replay: z.boolean(),
  resumed: z.boolean(),
});

export const evaluationSchema = z.object({
  session_id: z.string().uuid(),
  comparison: z.enum(["better", "same", "worse", "not_sure"]),
  explanation_usefulness: z.number().int().min(1).max(5),
  novelty_quality: z.number().int().min(1).max(5),
  comment: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
});

export const preferencesSchema = z.object({
  allow_explicit: z.boolean(),
  blocked_artists: z.array(z.object({ mbid: z.string().uuid(), name: z.string() })),
  blocked_recordings: z.array(z.object({ mbid: z.string().uuid(), name: z.string() })),
});

export type ProductUser = z.infer<typeof productUserSchema>;
export type Seed = z.infer<typeof seedSchema>;
export type MusicSearchResult = z.infer<typeof musicSearchResultSchema>;
export type DiscoveryJob = z.infer<typeof discoveryJobSchema>;
export type RecommendationSession = z.infer<typeof recommendationSessionSchema>;
export type RecommendationItem = z.infer<typeof recommendationItemSchema>;
export type Evidence = z.infer<typeof evidenceSchema>;
export type PlaylistExport = z.infer<typeof playlistExportSchema>;
export type Evaluation = z.infer<typeof evaluationSchema>;
export type Preferences = z.infer<typeof preferencesSchema>;
