import { describe, expect, it } from "vitest";

import { isStaleApplyError, parseAIBuilderError } from "./aiBuilderError";

describe("parseAIBuilderError", () => {
  it("parses SSE and HTTP apply errors to the same public contract", () => {
    const payload = {
      schema_version: 1,
      code: "planner_upstream_error",
      category: "upstream",
      message: "The AI planner failed. Please try again.",
      phase: "planner",
      intric_error_code: 9024,
      request_id: "req-1",
      context: { retryable: true }
    };

    const sseError = parseAIBuilderError({
      transport: "sse",
      payload: JSON.stringify(payload)
    });
    const httpError = parseAIBuilderError({
      transport: "apply",
      payload: { status: 502, response: payload }
    });

    expect(sseError).toEqual(httpError);
    expect(sseError.category).toBe("upstream");
    expect(sseError.request_id).toBe("req-1");
  });

  it("maps unmatched 409 responses to stale revision", () => {
    const parsed = parseAIBuilderError({
      transport: "apply",
      payload: {
        status: 409,
        response: {
          message: "Flow draft revision is stale.",
          context: { expected_revision: 3, current_revision: 4 }
        }
      }
    });

    expect(parsed).toMatchObject({
      schema_version: 1,
      code: "stale_revision",
      category: "conflict",
      message: "Flow draft revision is stale.",
      phase: "client",
      context: { expected_revision: 3, current_revision: 4 }
    });
    expect(isStaleApplyError(parsed)).toBe(true);
  });

  it("normalizes network failures into structured client errors", () => {
    const parsed = parseAIBuilderError({
      transport: "apply",
      payload: { status: 0, stage: "CONNECTION", message: "Network unavailable" }
    });

    expect(parsed).toMatchObject({
      code: "network",
      category: "network",
      message: "Network unavailable",
      phase: "client",
      context: { status: 0, stage: "CONNECTION" }
    });
  });

  it("drops non-scalar context values from client-side fallback parsing", () => {
    const parsed = parseAIBuilderError({
      transport: "apply",
      payload: {
        status: 400,
        response: {
          message: "Bad request",
          code: "legacy_code",
          context: {
            visible: "yes",
            nested: { hidden: true },
            list: ["hidden"]
          }
        }
      }
    });

    expect(parsed.context).toEqual({
      visible: "yes",
      status: 400,
      original_code: "legacy_code"
    });
  });
});
