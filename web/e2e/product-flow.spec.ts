import { expect, test, type Page, type Route } from "@playwright/test";

const SESSION_ID = "40000000-0000-4000-8000-000000000001";
const RECORDING_ID = "30000000-0000-4000-8000-000000000001";
const SEED_ID = "00000000-0000-4000-8000-000000000001";

test("anonymous sign in and public privacy notice", async ({ page }) => {
  await page.route("**/api/auth/me", (route) => json(route, 401, { detail: "Authentication required.", code: "authentication_required" }));
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "Outside the Loop" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Continue with Spotify" })).toHaveAttribute("href", "/api/auth/spotify/start?return_to=%2Fdiscover");
  await page.getByRole("link", { name: "privacy notice" }).click();
  await expect(page.getByRole("heading", { name: "Privacy at Outside the Loop" })).toBeVisible();
  await expect(page.getByText(/not local files or S3 objects/i)).toBeVisible();
});

test("recommendation is reviewed before named public playlist export", async ({ page }) => {
  const calls: { recommendation?: Record<string, unknown>; export?: Record<string, unknown> } = {};
  await mockApprovedProduct(page, calls);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/discover");

  await expect(page.getByText("Portishead", { exact: true })).toBeVisible();
  await page.getByLabel("Discovery prompt").fill("Late-night trip hop beyond the obvious names");
  await page.getByRole("radio", { name: "Adventurous" }).check();
  await page.getByRole("button", { name: "Find music" }).click();

  await expect(page).toHaveURL(`/sessions/${SESSION_ID}`);
  await expect(page.getByRole("heading", { name: "Roads" })).toBeVisible();
  await expect(page.getByText(/Listeners connect this recording/)).toBeVisible();
  await page.getByRole("button", { name: "Show evidence details" }).click();
  await expect(page.getByText("ListenBrainz")).toBeVisible();
  await page.getByRole("link", { name: "Review playlist" }).click();

  await page.getByLabel("Playlist name").fill("My Explicit Night Drive");
  await page.getByRole("checkbox", { name: "Public playlist" }).check();
  await page.getByRole("button", { name: "Create playlist" }).click();

  await expect(page.getByRole("link", { name: "Open playlist in Spotify" })).toHaveAttribute("href", "https://open.spotify.com/playlist/playlist-1");
  expect(calls.recommendation).toEqual({
    prompt: "Late-night trip hop beyond the obvious names",
    adventure: "adventurous",
    allow_explicit: true,
    seed_ids: [SEED_ID],
  });
  expect(calls.recommendation).not.toHaveProperty("create_playlist");
  expect(calls.export).toMatchObject({ name: "My Explicit Night Drive", public: true, recording_mbids: [RECORDING_ID] });
});

test("mobile navigation and discovery controls do not overflow", async ({ page }) => {
  await mockApprovedProduct(page, {});
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto("/discover");

  await expect(page.getByRole("navigation", { name: "Primary" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Find music" })).toBeVisible();
  const dimensions = await page.evaluate(() => ({ scrollWidth: document.documentElement.scrollWidth, clientWidth: document.documentElement.clientWidth }));
  expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth);
});

async function mockApprovedProduct(page: Page, calls: { recommendation?: Record<string, unknown>; export?: Record<string, unknown> }) {
  await page.route(/\/api\/(?:auth|me|discovery|music)(?:\/|$)/, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace(/^\/api/, "");
    if (path === "/auth/me") return json(route, 200, { display_name: "Tester", access_status: "approved", seed_ready: true, reauthorization_required: false });
    if (path === "/me/seeds" && request.method() === "GET") return json(route, 200, { seeds: [{ id: SEED_ID, entity_type: "artist", mbid: "8ab7aa79-24a4-4a5f-b2c6-3e3c2c7af95c", display_name: "Portishead", position: 1, source: "musicbrainz", selected_at: "2030-01-01T00:00:00Z" }] });
    if (path === "/discovery/jobs" && request.method() === "POST") return json(route, 202, discoveryJob("queued"));
    if (path === "/discovery/jobs/job-1") return json(route, 200, discoveryJob("ready"));
    if (path === "/me/recommendations" && request.method() === "POST") {
      calls.recommendation = request.postDataJSON() as Record<string, unknown>;
      return json(route, 201, recommendationSession("ready"));
    }
    if (path === `/me/recommendations/${SESSION_ID}` && request.method() === "GET") return json(route, 200, recommendationSession("ready"));
    if (path === `/me/recommendations/${SESSION_ID}/selection` && request.method() === "PUT") return json(route, 200, recommendationSession("reviewed"));
    if (path === `/me/recommendations/${SESSION_ID}/playlist` && request.method() === "POST") {
      calls.export = request.postDataJSON() as Record<string, unknown>;
      expect(request.headers()["idempotency-key"]).toBeTruthy();
      return json(route, 201, { id: "50000000-0000-4000-8000-000000000001", session_id: SESSION_ID, status: "complete", spotify_playlist_id: "playlist-1", spotify_playlist_url: "https://open.spotify.com/playlist/playlist-1", name: "My Explicit Night Drive", public: true, tracks_added: 1, track_count: 1, idempotent_replay: false, resumed: false });
    }
    return json(route, 404, { detail: `Unmocked ${request.method()} ${path}` });
  });
}

function discoveryJob(status: "queued" | "ready") {
  return { id: "job-1", status, source_adapters: ["listenbrainz_artist_radio"], attempt_count: status === "ready" ? 1 : 0, error_code: null, queued_at: "2030-01-01T00:00:00Z", started_at: null, completed_at: status === "ready" ? "2030-01-01T00:00:01Z" : null };
}

function recommendationSession(status: "ready" | "reviewed") {
  return {
    id: SESSION_ID,
    status,
    prompt: "Late-night trip hop beyond the obvious names",
    controls: { adventure: "adventurous", allow_explicit: true },
    intent: { label: "late-night", tags: ["trip hop"] },
    seed_ids: [SEED_ID],
    source_coverage: { status: "ready", evidence_coverage: 1 },
    ranking_version: "explicit-discovery-v1",
    generated_at: "2030-01-01T00:00:00Z",
    updated_at: "2030-01-01T00:00:00Z",
    review: { playlist_name: status === "reviewed" ? "My Explicit Night Drive" : null, public: status === "reviewed" ? true : null },
    recommendations: [{
      recording_mbid: RECORDING_ID,
      original_rank: 1,
      display: { spotify_track_id: "spotify-1", name: "Roads", artist_names: ["Portishead"], explicit: false, spotify_url: "https://open.spotify.com/track/spotify-1" },
      evidence: { recording_mbid: RECORDING_ID, evidence_version: "evidence-v1", verifiable: true, reasons: [{ kind: "source_edge", source: "listenbrainz", text: "Listeners connect this recording to your Portishead seed.", details: { adapter: "artist-radio" } }], limitations: [] },
      selected: true,
      reviewed_order: null,
    }],
  };
}

async function json(route: Route, status: number, body: unknown) {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}
