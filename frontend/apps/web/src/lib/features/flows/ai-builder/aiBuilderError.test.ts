import { describe, expect, it } from "vitest";

import type { AIBuilderError } from "./protocol";
import {
  classifyAIBuilderGenerationFailure,
  describeAIBuilderGenerationFailure,
  isStaleApplyError,
  parseAIBuilderError
} from "./aiBuilderError";

describe("parseAIBuilderError", () => {
  it("parses SSE and HTTP apply errors to the same public contract", () => {
    const payload = {
      schema_version: 2,
      code: "planner_upstream_error",
      category: "upstream",
      message: "The AI planner failed. Please try again.",
      phase: "planner",
      eneo_error_code: 9024,
      request_id: "req-1",
      diagnostic_context: {
        request_id: "req-1",
        session_id: "session-1",
        error_code: "planner_upstream_error",
        error_category: "upstream",
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
    expect(sseError.category).toBe("upstream");
    expect(sseError.request_id).toBe("req-1");
    expect(sseError.diagnostic_context?.session_id).toBe("session-1");
    expect(sseError.details.retryable).toBe(true);
  });

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

describe("classifyAIBuilderGenerationFailure", () => {
  const error = (overrides: Partial<AIBuilderError>): AIBuilderError => ({
    schema_version: 2,
    code: "unknown",
    category: "internal",
    message: "Modellen svarade inte i tid.",
    phase: "planner",
    request_id: "req-1",
    eneo_error_code: null,
    diagnostic_context: null,
    details: {},
    ...overrides
  });
  const rejected = {
    another_call_permitted: false,
    provider_disposition: "known_rejection",
    retry_scope: "new_turn"
  };

  it.each([
    [
      "an unknown provider outcome from the turn state, whatever the payload says",
      error({ code: "planner_upstream_error", category: "upstream", details: rejected }),
      "provider_outcome_unknown",
      "provider_outcome_unknown"
    ],
    [
      "a transport failure this client saw",
      error({ code: "network", category: "network", phase: "client" }),
      null,
      "network"
    ],
    [
      "a provider rejection",
      error({ code: "planner_upstream_error", category: "upstream", details: rejected }),
      null,
      "provider_rejected"
    ],
    [
      "an exhausted request budget",
      error({ code: "planner_context_limit_exceeded", category: "upstream" }),
      null,
      "request_budget_exhausted"
    ],
    [
      "a truncated model answer",
      error({ code: "planner_output_too_long", category: "upstream" }),
      null,
      "output_too_long"
    ],
    [
      "an invalid proposal after repairs",
      error({ code: "self_correction_invalid_plan", phase: "self_correction" }),
      null,
      "invalid_proposal"
    ],
    [
      "a server-reported stream failure as the quoted fallback, never as a connection loss",
      error({ code: "planner_stream_failed", category: "upstream" }),
      null,
      "other"
    ]
  ] as const)("classifies %s", (_name, failure, turnRecoveryState, kind) => {
    expect(classifyAIBuilderGenerationFailure(failure, turnRecoveryState)).toBe(kind);
  });

  it("quotes the server message only for the fallback class", () => {
    const fallback = describeAIBuilderGenerationFailure(
      error({ code: "planner_stream_failed", category: "upstream" }),
      null
    );
    expect(fallback.body).toBe("Modellen svarade inte i tid.");
    const rejection = describeAIBuilderGenerationFailure(
      error({ code: "planner_upstream_error", category: "upstream", details: rejected }),
      null
    );
    expect(rejection.body).not.toBe("Modellen svarade inte i tid.");
  });
});
