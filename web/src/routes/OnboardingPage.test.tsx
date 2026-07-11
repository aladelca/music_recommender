import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { api } from "../api/client";
import { OnboardingPage } from "./OnboardingPage";

const refresh = vi.fn();

vi.mock("../auth/useAuth", () => ({
  useAuth: () => ({ user: null, loading: false, refresh, logout: vi.fn() }),
}));

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return {
    ...actual,
    api: { ...actual.api, searchMusic: vi.fn(), replaceSeeds: vi.fn() },
  };
});

describe("OnboardingPage", () => {
  it("searches MusicBrainz and persists only confirmed seeds", async () => {
    const user = userEvent.setup();
    vi.mocked(api.searchMusic).mockResolvedValue({
      source: "musicbrainz",
      cached: false,
      results: [{
        mbid: "8ab7aa79-24a4-4a5f-b2c6-3e3c2c7af95c",
        entity_type: "artist",
        name: "Portishead",
        artist_credit: [],
        release_data: {},
        isrcs: [],
        source: "musicbrainz",
      }],
    });
    vi.mocked(api.replaceSeeds).mockResolvedValue({ seeds: [] });
    renderPage();

    await user.type(screen.getByLabelText("Search MusicBrainz"), "Portishead");
    await user.click(screen.getByRole("button", { name: "Search" }));
    await user.click(await screen.findByRole("button", { name: "Add Portishead" }));
    await user.click(screen.getByRole("button", { name: "Save seeds" }));

    expect(api.replaceSeeds).toHaveBeenCalledWith([{ entity_type: "artist", mbid: "8ab7aa79-24a4-4a5f-b2c6-3e3c2c7af95c" }]);
    expect(refresh).toHaveBeenCalled();
  });
});

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={queryClient}><MemoryRouter><OnboardingPage /></MemoryRouter></QueryClientProvider>);
}
