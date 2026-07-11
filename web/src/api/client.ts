import { z, type ZodType } from "zod";

import {
  discoveryJobSchema,
  evaluationSchema,
  historySchema,
  musicSearchResponseSchema,
  playlistExportSchema,
  preferencesSchema,
  productUserSchema,
  recommendationSessionSchema,
  seedsResponseSchema,
} from "./schemas";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code?: string,
  ) {
    super(message);
  }
}

type RequestOptions = {
  method?: "GET" | "POST" | "PUT" | "DELETE";
  body?: unknown;
  headers?: Record<string, string>;
};

function csrfToken(): string | undefined {
  const prefix = "__Host-mr_csrf=";
  return document.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(prefix))
    ?.slice(prefix.length);
}

async function request<T>(
  path: string,
  schema: ZodType<T>,
  options: RequestOptions = {},
): Promise<T> {
  const method = options.method ?? "GET";
  const headers = new Headers(options.headers);
  if (options.body !== undefined) headers.set("Content-Type", "application/json");
  if (method !== "GET") {
    const token = csrfToken();
    if (token) headers.set("X-CSRF-Token", decodeURIComponent(token));
  }
  const response = await fetch(`/api${path}`, {
    method,
    credentials: "include",
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => ({}))) as {
      detail?: string;
      code?: string;
    };
    throw new ApiError(payload.detail ?? "The request could not be completed.", response.status, payload.code);
  }
  const parsed = schema.safeParse(await response.json());
  if (!parsed.success) {
    throw new ApiError("The server returned an invalid response.", 502, "invalid_response");
  }
  return parsed.data;
}

export const api = {
  me: () => request("/auth/me", productUserSchema),
  logout: () => requestNoContent("/auth/logout", { method: "POST" }),
  deleteAccount: () =>
    requestNoContent("/auth/me", { method: "DELETE", body: { confirmation: "DELETE" } }),
  searchMusic: (query: string, type: "artist" | "recording") =>
    request(
      `/music/search?q=${encodeURIComponent(query)}&type=${type}`,
      musicSearchResponseSchema,
    ),
  seeds: () => request("/me/seeds", seedsResponseSchema),
  replaceSeeds: (seeds: Array<{ entity_type: "artist" | "recording"; mbid: string }>) =>
    request("/me/seeds", seedsResponseSchema, { method: "PUT", body: { seeds } }),
  startDiscovery: () => request("/discovery/jobs", discoveryJobSchema, { method: "POST" }),
  discoveryJob: (jobId: string) => request(`/discovery/jobs/${jobId}`, discoveryJobSchema),
  generateRecommendations: (body: {
    prompt: string;
    adventure: "familiar" | "balanced" | "adventurous";
    allow_explicit: boolean;
    seed_ids: string[];
  }) => request("/me/recommendations", recommendationSessionSchema, { method: "POST", body }),
  recommendation: (sessionId: string) =>
    request(`/me/recommendations/${sessionId}`, recommendationSessionSchema),
  recommendationHistory: (cursor?: string) =>
    request(
      `/me/recommendations?limit=20${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
      historySchema,
    ),
  reviewRecommendation: (
    sessionId: string,
    body: { recording_mbids: string[]; playlist_name: string; public: boolean },
  ) =>
    request(`/me/recommendations/${sessionId}/selection`, recommendationSessionSchema, {
      method: "PUT",
      body,
    }),
  exportPlaylist: (
    sessionId: string,
    body: {
      name: string;
      description: string;
      public: boolean;
      recording_mbids: string[];
    },
    idempotencyKey: string,
  ) =>
    request(`/me/recommendations/${sessionId}/playlist`, playlistExportSchema, {
      method: "POST",
      body,
      headers: { "Idempotency-Key": idempotencyKey },
    }),
  feedback: (
    sessionId: string,
    body: { recording_mbid: string; event_type: "like" | "dislike" | "hide_artist" | "save" | "skip" },
    idempotencyKey: string,
  ) =>
    request(`/me/recommendations/${sessionId}/feedback`, feedbackResponseSchema, {
      method: "POST",
      body,
      headers: { "Idempotency-Key": idempotencyKey },
    }),
  saveEvaluation: (
    sessionId: string,
    body: {
      comparison: "better" | "same" | "worse" | "not_sure";
      explanation_usefulness: number;
      novelty_quality: number;
      comment: string | null;
    },
  ) => request(`/me/recommendations/${sessionId}/evaluation`, evaluationSchema, { method: "PUT", body }),
  preferences: () => request("/me/preferences", preferencesSchema),
  unblockArtist: (artistMbid: string) =>
    request(`/me/preferences/artists/${artistMbid}`, preferencesSchema, { method: "DELETE" }),
};

const feedbackResponseSchema = z.object({
  event_id: z.string().uuid(),
  status: z.literal("recorded"),
  event_type: z.string(),
  recording_mbid: z.string().uuid(),
  idempotent_replay: z.boolean(),
});

async function requestNoContent(path: string, options: RequestOptions): Promise<void> {
  const method = options.method ?? "POST";
  const headers = new Headers(options.headers);
  if (options.body !== undefined) headers.set("Content-Type", "application/json");
  const token = csrfToken();
  if (token) headers.set("X-CSRF-Token", decodeURIComponent(token));
  const response = await fetch(`/api${path}`, {
    method,
    credentials: "include",
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => ({}))) as { detail?: string; code?: string };
    throw new ApiError(payload.detail ?? "The request could not be completed.", response.status, payload.code);
  }
}
