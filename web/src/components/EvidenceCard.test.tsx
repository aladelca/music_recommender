import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { EvidenceCard } from "./EvidenceCard";

describe("EvidenceCard", () => {
  it("shows the explanation first and expands source provenance", async () => {
    const user = userEvent.setup();
    render(
      <EvidenceCard
        evidence={{
          recording_mbid: "00000000-0000-0000-0000-000000000001",
          evidence_version: "evidence-v1",
          verifiable: true,
          reasons: [
            {
              kind: "source_edge",
              source: "listenbrainz",
              text: "Listeners connect this recording to your Portishead seed.",
              details: { adapter: "artist-radio", seed_name: "Portishead" },
            },
          ],
          limitations: ["Explicit status is supplied by Spotify after ranking."],
        }}
      />,
    );

    expect(screen.getByText(/Listeners connect this recording/)).toBeVisible();
    expect(screen.queryByText("artist-radio")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Show evidence details" }));

    expect(screen.getByText("ListenBrainz")).toBeVisible();
    expect(screen.getByText(/artist-radio/)).toBeVisible();
    expect(screen.getByText(/Explicit status is supplied/)).toBeVisible();
  });
});
