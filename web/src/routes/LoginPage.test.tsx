import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { LoginPage } from "./LoginPage";

describe("LoginPage", () => {
  it("starts the same-origin Spotify OAuth flow", () => {
    render(<MemoryRouter><LoginPage /></MemoryRouter>);

    expect(screen.getByRole("link", { name: "Continue with Spotify" })).toHaveAttribute(
      "href",
      "/api/auth/spotify/start?return_to=%2Fdiscover",
    );
  });

  it("makes reconnect state explicit", () => {
    render(<MemoryRouter><LoginPage reconnect /></MemoryRouter>);

    expect(screen.getByRole("heading", { name: "Reconnect Spotify" })).toBeVisible();
    expect(screen.getByRole("link", { name: "Reconnect Spotify" })).toBeVisible();
  });
});
