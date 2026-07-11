import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { api } from "../api/client";
import { SessionEvaluation } from "./SessionEvaluation";

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return { ...actual, api: { ...actual.api, saveEvaluation: vi.fn() } };
});

describe("SessionEvaluation", () => {
  it("submits the frozen beta comparison and ratings", async () => {
    const user = userEvent.setup();
    vi.mocked(api.saveEvaluation).mockResolvedValue({
      session_id: "40000000-0000-0000-0000-000000000001",
      comparison: "better",
      explanation_usefulness: 5,
      novelty_quality: 4,
      comment: "Clear evidence",
      created_at: "2030-01-01T00:00:00Z",
      updated_at: "2030-01-01T00:00:00Z",
    });
    const queryClient = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    render(<QueryClientProvider client={queryClient}><SessionEvaluation sessionId="40000000-0000-0000-0000-000000000001" /></QueryClientProvider>);

    await user.click(screen.getByRole("radio", { name: "Better" }));
    await user.clear(screen.getByLabelText("Explanation usefulness"));
    await user.type(screen.getByLabelText("Explanation usefulness"), "5");
    await user.clear(screen.getByLabelText("Novelty quality"));
    await user.type(screen.getByLabelText("Novelty quality"), "4");
    await user.type(screen.getByLabelText("Optional comment"), "Clear evidence");
    await user.click(screen.getByRole("button", { name: "Save evaluation" }));

    expect(api.saveEvaluation).toHaveBeenCalledWith("40000000-0000-0000-0000-000000000001", {
      comparison: "better",
      explanation_usefulness: 5,
      novelty_quality: 4,
      comment: "Clear evidence",
    });
    expect(await screen.findByText("Evaluation saved")).toBeVisible();
  });
});
