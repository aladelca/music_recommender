import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { api } from "../api/client";
import { SettingsPage } from "./SettingsPage";

vi.mock("../auth/useAuth", () => ({ useAuth: () => ({ user: { display_name: "Tester" }, logout: vi.fn(), refresh: vi.fn(), loading: false }) }));
vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return { ...actual, api: { ...actual.api, preferences: vi.fn(), unblockArtist: vi.fn(), deleteAccount: vi.fn() } };
});

describe("SettingsPage", () => {
  it("lists account blocks and requires the exact deletion confirmation", async () => {
    const user = userEvent.setup();
    vi.mocked(api.preferences).mockResolvedValue({ allow_explicit: true, blocked_artists: [{ mbid: "00000000-0000-0000-0000-000000000001", name: "Portishead" }], blocked_recordings: [] });
    vi.mocked(api.deleteAccount).mockResolvedValue();
    renderPage();

    expect(await screen.findByText("Portishead")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Delete account" }));
    expect(screen.getByRole("button", { name: "Delete permanently" })).toBeDisabled();
    await user.type(screen.getByLabelText("Type DELETE to confirm"), "DELETE");
    await user.click(screen.getByRole("button", { name: "Delete permanently" }));

    expect(api.deleteAccount).toHaveBeenCalledOnce();
  });
});

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={queryClient}><MemoryRouter><SettingsPage /></MemoryRouter></QueryClientProvider>);
}
