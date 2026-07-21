import { EneoError } from "@eneo/eneo-js";
import { describe, expect, it, vi } from "vitest";

vi.mock("$lib/paraglide/messages", () => ({
  m: {
    eneo_error_9042: () => "Credential encryption must be configured before saving secrets.",
    request_failed: () => "Request failed."
  }
}));

import { getErrorMessage } from "./getErrorMessage";

describe("getErrorMessage", () => {
  it("localizes missing credential encryption configuration", () => {
    const error = new EneoError(
      "Backend fallback",
      "RESPONSE",
      503,
      9042,
      {},
      { endpoint: "POST@/api/v1/admin/model-providers/" }
    );

    expect(getErrorMessage(error)).toBe(
      "Credential encryption must be configured before saving secrets."
    );
  });
});
