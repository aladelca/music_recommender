import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "./client";

describe("API client response validation", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("does not expose Zod diagnostics for an invalid backend response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ display_name: 7 }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    })));

    await expect(api.me()).rejects.toMatchObject({
      message: "The server returned an invalid response.",
      status: 502,
      code: "invalid_response",
    });
  });
});
