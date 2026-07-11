import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "../api/client";
import { ReviewPage } from "./ReviewPage";

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      recommendation: vi.fn(),
      reviewRecommendation: vi.fn(),
      exportPlaylist: vi.fn(),
    },
  };
});

describe("ReviewPage", () => {
  beforeEach(() => {
    vi.mocked(api.recommendation).mockResolvedValue(session());
    vi.mocked(api.reviewRecommendation).mockResolvedValue({ ...session(), status: "reviewed" });
    vi.mocked(api.exportPlaylist).mockResolvedValue({
      id: "50000000-0000-0000-0000-000000000001",
      session_id: SESSION_ID,
      status: "complete",
      spotify_playlist_id: "playlist-1",
      spotify_playlist_url: "https://open.spotify.com/playlist/playlist-1",
      name: "My Night Drive",
      public: true,
      tracks_added: 1,
      track_count: 1,
      idempotent_replay: false,
      resumed: false,
    });
  });

  it("reviews before exporting with the explicit name and visibility", async () => {
    const user = userEvent.setup();
    renderPage();

    expect(await screen.findByDisplayValue("Outside the Loop - Late night trip hop")).toBeVisible();
    await user.clear(screen.getByLabelText("Playlist name"));
    await user.type(screen.getByLabelText("Playlist name"), "My Night Drive");
    await user.click(screen.getByRole("checkbox", { name: "Public playlist" }));
    await user.click(screen.getByRole("button", { name: "Create playlist" }));

    expect(api.reviewRecommendation).toHaveBeenCalledWith(SESSION_ID, {
      recording_mbids: [RECORDING_ID],
      playlist_name: "My Night Drive",
      public: true,
    });
    expect(api.exportPlaylist).toHaveBeenCalledWith(
      SESSION_ID,
      {
        name: "My Night Drive",
        description: "Discovered with Outside the Loop",
        public: true,
        recording_mbids: [RECORDING_ID],
      },
      expect.any(String),
    );
    expect(await screen.findByRole("link", { name: "Open playlist in Spotify" })).toBeVisible();
  });
});

const SESSION_ID = "40000000-0000-0000-0000-000000000001";
const RECORDING_ID = "30000000-0000-0000-0000-000000000001";

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[`/sessions/${SESSION_ID}/review`]}>
        <Routes>
          <Route path="/sessions/:sessionId/review" element={<ReviewPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function session() {
  return {
    id: SESSION_ID,
    status: "ready" as const,
    prompt: "Late night trip hop",
    controls: { adventure: "balanced" },
    intent: { label: "seed-led", tags: [] },
    seed_ids: ["00000000-0000-0000-0000-000000000001"],
    source_coverage: { status: "ready", evidence_coverage: 1 },
    ranking_version: "explicit-discovery-v1",
    generated_at: "2030-01-01T00:00:00Z",
    updated_at: "2030-01-01T00:00:00Z",
    review: { playlist_name: null, public: null },
    recommendations: [
      {
        recording_mbid: RECORDING_ID,
        original_rank: 1,
        display: {
          spotify_track_id: "spotify-1",
          name: "Roads",
          artist_names: ["Portishead"],
          explicit: false,
          spotify_url: "https://open.spotify.com/track/spotify-1",
        },
        evidence: {
          recording_mbid: RECORDING_ID,
          evidence_version: "evidence-v1",
          verifiable: true,
          reasons: [],
          limitations: [],
        },
        selected: true,
        reviewed_order: null,
      },
    ],
  };
}
