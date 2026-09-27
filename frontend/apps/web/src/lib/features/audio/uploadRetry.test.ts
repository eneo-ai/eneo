import { EneoError } from "@eneo/eneo-js";
import { describe, expect, it } from "vitest";
import { isTransientUploadFailure, UploadTimeoutError } from "./uploadRetry";

const eneoError = (stage: "CONNECTION" | "SERVER" | "RESPONSE", status: number) =>
  new EneoError("failed", stage, status, 0);

describe("isTransientUploadFailure", () => {
  it("retries the network, timeouts and a busy or failing server", () => {
    expect(isTransientUploadFailure(new TypeError("Failed to fetch"))).toBe(true);
    expect(isTransientUploadFailure(new UploadTimeoutError("The upload timed out"))).toBe(true);
    expect(isTransientUploadFailure(eneoError("CONNECTION", 0))).toBe(true);
    for (const status of [408, 429, 500, 502, 503]) {
      expect(isTransientUploadFailure(eneoError("SERVER", status))).toBe(true);
    }
  });

  it("leaves a refusal, and any failure it cannot tell, to the user", () => {
    expect(isTransientUploadFailure(new Error("something else"))).toBe(false);
    for (const status of [400, 401, 403, 404, 409, 413, 415, 422]) {
      expect(isTransientUploadFailure(eneoError("SERVER", status))).toBe(false);
    }
  });
});
