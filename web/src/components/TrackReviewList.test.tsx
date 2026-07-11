import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { RecommendationItem } from "../api/schemas";
import { TrackReviewList } from "./TrackReviewList";

const items = [track("00000000-0000-0000-0000-000000000001", "Roads"), track("00000000-0000-0000-0000-000000000002", "Glory Box")];

describe("TrackReviewList", () => {
  it("reorders and removes tracks with labelled controls", async () => {
    const user = userEvent.setup();
    let current = items;
    const view = render(<TrackReviewList items={current} onChange={update} />);

    function update(next: RecommendationItem[]) {
      current = next;
      view.rerender(<TrackReviewList items={current} onChange={update} />);
    }

    await user.click(screen.getByRole("button", { name: "Move Glory Box up" }));
    expect(screen.getAllByTestId("review-track").map((node) => node.textContent)).toEqual([
      expect.stringContaining("Glory Box"),
      expect.stringContaining("Roads"),
    ]);

    await user.click(screen.getByRole("button", { name: "Remove Glory Box" }));
    expect(screen.queryByText("Glory Box")).not.toBeInTheDocument();
    expect(screen.getByText("Roads")).toBeVisible();
  });
});

function track(recording_mbid: string, name: string): RecommendationItem {
  return {
    recording_mbid,
    original_rank: 1,
    display: {
      spotify_track_id: recording_mbid.slice(-8),
      name,
      artist_names: ["Portishead"],
      explicit: false,
      spotify_url: `https://open.spotify.com/track/${recording_mbid.slice(-8)}`,
    },
    evidence: {
      recording_mbid,
      evidence_version: "evidence-v1",
      verifiable: true,
      reasons: [],
      limitations: [],
    },
    selected: true,
    reviewed_order: null,
  };
}
