import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { DiscoveryForm } from "./DiscoveryForm";

describe("DiscoveryForm", () => {
  it("submits only explicit product controls and selected seed ids", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(
      <DiscoveryForm
        seeds={[
          {
            id: "00000000-0000-0000-0000-000000000001",
            entity_type: "artist",
            mbid: "00000000-0000-0000-0000-000000000002",
            display_name: "Portishead",
            position: 1,
            source: "musicbrainz",
            selected_at: "2030-01-01T00:00:00Z",
          },
        ]}
        onSubmit={onSubmit}
        pending={false}
      />,
    );

    await user.type(screen.getByLabelText("Discovery prompt"), "Late-night trip hop beyond the usual names");
    await user.click(screen.getByRole("radio", { name: "Adventurous" }));
    await user.click(screen.getByRole("checkbox", { name: "Allow explicit tracks" }));
    await user.click(screen.getByRole("button", { name: "Find music" }));

    expect(onSubmit).toHaveBeenCalledWith({
      prompt: "Late-night trip hop beyond the usual names",
      adventure: "adventurous",
      allow_explicit: false,
      seed_ids: ["00000000-0000-0000-0000-000000000001"],
    });
  });

  it("does not submit a one-character prompt", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(<DiscoveryForm seeds={[]} onSubmit={onSubmit} pending={false} />);

    await user.type(screen.getByLabelText("Discovery prompt"), "x");
    await user.click(screen.getByRole("button", { name: "Find music" }));

    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent("Enter at least two characters");
  });
});
