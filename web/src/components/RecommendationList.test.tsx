import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import type { RecommendationItem } from "../api/schemas";
import { RecommendationList } from "./RecommendationList";

describe("RecommendationList", () => {
  it("keeps exactly one Spotify embed active", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.click(screen.getAllByRole("button", { name: "Preview" })[0]);
    expect(screen.getAllByLabelText(/Spotify preview for/)).toHaveLength(1);
    expect(screen.getByLabelText("Spotify preview for Roads")).toBeVisible();

    await user.click(screen.getAllByRole("button", { name: "Preview" })[0]);
    expect(screen.getAllByLabelText(/Spotify preview for/)).toHaveLength(1);
    expect(screen.getByLabelText("Spotify preview for Glory Box")).toBeVisible();
  });
});

function Harness() {
  const [active, setActive] = useState<string | null>(null);
  return <RecommendationList items={[track("30000000-0000-4000-8000-000000000001", "spotify-1", "Roads"), track("30000000-0000-4000-8000-000000000002", "spotify-2", "Glory Box")]} activeTrackId={active} feedbackTrackId={null} onPreview={setActive} onFeedback={vi.fn()} />;
}

function track(recording_mbid: string, spotify_track_id: string, name: string): RecommendationItem {
  return {
    recording_mbid,
    original_rank: 1,
    display: { spotify_track_id, name, artist_names: ["Portishead"], explicit: false, spotify_url: `https://open.spotify.com/track/${spotify_track_id}` },
    evidence: { recording_mbid, evidence_version: "evidence-v1", verifiable: true, reasons: [], limitations: [] },
    selected: true,
    reviewed_order: null,
  };
}
