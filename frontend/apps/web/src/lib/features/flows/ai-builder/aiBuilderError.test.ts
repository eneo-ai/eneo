import { describe, expect, it } from "vitest";
import { m } from "$lib/paraglide/messages";

import { isStaleApplyError, parseAIBuilderError } from "./aiBuilderError";

describe("parseAIBuilderError", () => {
  it.each([
    ["planner_upstream_error", "upstream", "The AI planner failed. Please try again."],
    ["flow_owner_required", "unauthorized", m.flow_error_flow_owner_required()]
  ])(
    "preserves %s in SSE and HTTP errors with localized owner refusal",
    (code, category, message) => {
      const payload = {
        schema_version: 2,
        code,
        category,
        message: "The AI planner failed. Please try again.",
        phase: "planner",
        eneo_error_code: 9024,
        request_id: "req-1",
        diagnostic_context: {
          request_id: "req-1",
          session_id: "session-1",
          error_code: code,
          error_category: category,
          error_phase: "planner"
        },
        details: { retryable: true }
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
      expect(sseError.code).toBe(code);
      expect(sseError.category).toBe(category);
      expect(sseError.message).toBe(message);
      expect(sseError.request_id).toBe("req-1");
      expect(sseError.diagnostic_context?.session_id).toBe("session-1");
      expect(sseError.details.retryable).toBe(true);
    }
  );

  it("maps unmatched 409 responses to stale revision", () => {
    const parsed = parseAIBuilderError({
      transport: "apply",
      payload: {
        status: 409,
        response: {
          message: "Flow draft revision is stale.",
          details: { expected_revision: 3, current_revision: 4 }
        }
      }
    });

    expect(parsed).toMatchObject({
      schema_version: 2,
      code: "stale_revision",
      category: "conflict",
      message: "Flow draft revision is stale.",
      phase: "client",
      diagnostic_context: null,
      details: { expected_revision: 3, current_revision: 4 }
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
      details: { status: 0, stage: "CONNECTION" }
    });
  });

  it("drops non-scalar detail values from client-side fallback parsing", () => {
    const parsed = parseAIBuilderError({
      transport: "apply",
      payload: {
        status: 400,
        response: {
          message: "Bad request",
          code: "legacy_code",
          details: {
            visible: "yes",
            nested: { hidden: true },
            list: ["hidden"]
          }
        }
      }
    });

    expect(parsed.details).toEqual({
      visible: "yes",
      status: 400,
      original_code: "legacy_code"
    });
  });
});
