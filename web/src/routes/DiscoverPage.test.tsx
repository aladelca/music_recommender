import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { api } from "../api/client";
import { DiscoverPage } from "./DiscoverPage";

const navigate = vi.fn();

vi.mock("react-router-dom", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-router-dom")>();
  return { ...actual, useNavigate: () => navigate };
});

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      seeds: vi.fn(),
      startDiscovery: vi.fn(),
      discoveryJob: vi.fn(),
      generateRecommendations: vi.fn(),
    },
  };
});

describe("DiscoverPage", () => {
  it("waits for automated source discovery before generating a read-only session", async () => {
    const user = userEvent.setup();
    vi.mocked(api.seeds).mockResolvedValue({ seeds: [seed()] });
    vi.mocked(api.startDiscovery).mockImplementation(async () => {
      await new Promise((resolve) => setTimeout(resolve, 50));
      return job("queued");
    });
    vi.mocked(api.discoveryJob).mockResolvedValue(job("ready"));
    vi.mocked(api.generateRecommendations).mockResolvedValue(recommendation());
    renderPage();

    await screen.findByText("Portishead");
    await user.type(screen.getByLabelText("Discovery prompt"), "Dub-informed ambient pop");
    await user.click(screen.getByRole("button", { name: "Find music" }));

    expect(await screen.findByText("Gathering source evidence")).toBeVisible();
    await waitFor(() => expect(api.generateRecommendations).toHaveBeenCalledWith({
      prompt: "Dub-informed ambient pop",
      adventure: "balanced",
      allow_explicit: true,
      seed_ids: [seed().id],
    }), { timeout: 4_000 });
    expect(navigate).toHaveBeenCalledWith(`/sessions/${recommendation().id}`);
  });
});

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={queryClient}><MemoryRouter><DiscoverPage pollIntervalMs={1} /></MemoryRouter></QueryClientProvider>);
}

function seed() {
  return { id: "00000000-0000-0000-0000-000000000001", entity_type: "artist" as const, mbid: "00000000-0000-0000-0000-000000000002", display_name: "Portishead", position: 1, source: "musicbrainz" as const, selected_at: "2030-01-01T00:00:00Z" };
}

function job(status: "queued" | "ready") {
  return { id: "job-1", status, source_adapters: ["listenbrainz_artist_radio"], attempt_count: status === "ready" ? 1 : 0, error_code: null, queued_at: "2030-01-01T00:00:00Z", started_at: null, completed_at: status === "ready" ? "2030-01-01T00:00:01Z" : null };
}

function recommendation() {
  return { id: "40000000-0000-0000-0000-000000000001", status: "ready" as const, prompt: "Dub-informed ambient pop", controls: {}, intent: {}, seed_ids: [seed().id], source_coverage: {}, ranking_version: "explicit-discovery-v1", generated_at: "2030-01-01T00:00:00Z", updated_at: "2030-01-01T00:00:00Z", review: { playlist_name: null, public: null }, recommendations: [] };
}
