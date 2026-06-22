import { describe, expect, it } from "vitest";

import { shouldSerializeBackendResponseHeader } from "./serializedBackendResponseHeaders";

describe("shouldSerializeBackendResponseHeader", () => {
  it("serializes backend trace headers across casing variants", () => {
    expect(shouldSerializeBackendResponseHeader("x-trace-id")).toBe(true);
    expect(shouldSerializeBackendResponseHeader("X-Trace-Id")).toBe(true);
    expect(shouldSerializeBackendResponseHeader("x-correlation-id")).toBe(true);
    expect(shouldSerializeBackendResponseHeader("X-Correlation-ID")).toBe(true);
    expect(shouldSerializeBackendResponseHeader("x-error-code")).toBe(true);
    expect(shouldSerializeBackendResponseHeader("X-Error-Code")).toBe(true);
  });

  it("does not serialize unrelated backend headers", () => {
    expect(shouldSerializeBackendResponseHeader("set-cookie")).toBe(false);
    expect(shouldSerializeBackendResponseHeader("authorization")).toBe(false);
    expect(shouldSerializeBackendResponseHeader("x-powered-by")).toBe(false);
  });
});
