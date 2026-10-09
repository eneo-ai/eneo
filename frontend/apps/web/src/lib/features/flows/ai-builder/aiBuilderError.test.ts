import { describe, expect, it } from "vitest";
import { m } from "$lib/paraglide/messages";

import {
  aiBuilderErrorCopy,
  aiBuilderErrorText,
  AIBuilderClientRefusal,
  isStaleApplyError,
  parseAIBuilderError
} from "./aiBuilderError";
import type { AIBuilderError } from "./protocol";

const ENGLISH_SERVER_MESSAGE = "The AI planner failed. Please try again.";

function serverError(
  code: string,
  details: AIBuilderError["details"] = {},
  category: AIBuilderError["category"] = "bad_request"
): AIBuilderError {
  return {
    schema_version: 2,
    code,
    category,
    message: ENGLISH_SERVER_MESSAGE,
    phase: "planner",
    request_id: "req-1",
    diagnostic_context: null,
    details
  };
}

describe("aiBuilderErrorText", () => {
  it.each([
    ["model_not_available", {}, m.ai_builder_model_not_listed()],
    ["no_planner_model_available", {}, m.ai_builder_no_ready_model()],
    ["planner_model_missing_context_window", {}, m.ai_builder_model_capacity_undeclared()],
    ["planner_model_incompatible_token_limits", {}, m.ai_builder_model_capacity_too_small()],
    ["flow_owner_required", {}, m.flow_error_flow_owner_required()],
    ["session_message_in_progress", {}, m.ai_builder_error_request_in_progress()],
    ["stale_revision", {}, m.ai_builder_error_flow_changed()],
    [
      "bad_request",
      { max_chars: 4000, actual_chars: 4100 },
      m.ai_builder_error_message_too_long({ max: "4000" })
    ],
    [
      "planner_upstream_error",
      { provider_exception_class: "rate_limit" },
      m.ai_builder_error_provider_rate_limited()
    ],
    [
      "architecture_materialization_failed",
      { architecture_repair_disposition: "user_action" },
      m.ai_builder_error_requirements_unbuildable()
    ]
  ])("says %s in the reader's language", (code, details, expected) => {
    const error = serverError(code, details);
    expect(aiBuilderErrorText(error)).toBe(expected);
    expect(aiBuilderErrorText(error)).not.toContain(ENGLISH_SERVER_MESSAGE);
  });

  it("falls back to the failed operation's sentence, never the server's prose", () => {
    const parsed = parseAIBuilderError({
      transport: "sse",
      payload: JSON.stringify({
        ...serverError("planner_stream_failed", {}, "internal"),
        eneo_error_code: 9024
      }),
      fallbackMessage: m.ai_builder_error_fallback_stream()
    });
    expect(parsed.message).toBe(ENGLISH_SERVER_MESSAGE);
    expect(aiBuilderErrorCopy(parsed)).toBeNull();
    expect(aiBuilderErrorText(parsed)).toBe(m.ai_builder_error_fallback_stream());
  });

  it("keeps an unknown legacy code's English message out of the UI", () => {
    const parsed = parseAIBuilderError({
      transport: "apply",
      payload: { status: 400, response: { message: "Bad request", code: "legacy_code" } },
      fallbackMessage: m.ai_builder_error_fallback_apply_plan()
    });
    expect(parsed.message).toBe("Bad request");
    expect(aiBuilderErrorText(parsed)).toBe(m.ai_builder_error_fallback_apply_plan());
  });

  it("uses the generic sentence when the error carries no operation", () => {
    expect(aiBuilderErrorText(serverError("not_a_known_code"))).toBe(
      m.ai_builder_error_fallback_generic()
    );
  });

  it("reads a client refusal by its code, not its developer message", () => {
    const missingFlow = parseAIBuilderError({
      transport: "apply",
      payload: new AIBuilderClientRefusal("edit_session_flow_required"),
      fallbackMessage: m.ai_builder_review_load_failed()
    });
    expect(missingFlow.code).toBe("edit_session_flow_required");
    expect(aiBuilderErrorText(missingFlow)).toBe(m.ai_builder_error_edit_needs_flow());

    const blocked = parseAIBuilderError({
      transport: "apply",
      payload: new AIBuilderClientRefusal("model_send_blocked", { reason: "model_not_listed" }),
      fallbackMessage: m.ai_builder_review_suggestions_failed()
    });
    expect(aiBuilderErrorText(blocked)).toBe(m.ai_builder_model_not_listed());
  });

  it("reads a network loss as a lost connection", () => {
    const parsed = parseAIBuilderError({
      transport: "apply",
      payload: { status: 0, stage: "CONNECTION", message: "Network unavailable" }
    });
    expect(aiBuilderErrorText(parsed)).toBe(m.ai_builder_error_network());
  });
});

describe("parseAIBuilderError", () => {
  it.each([
    ["planner_upstream_error", "upstream", ENGLISH_SERVER_MESSAGE],
    ["flow_owner_required", "unauthorized", ENGLISH_SERVER_MESSAGE]
  ])(
    "preserves %s and the server's diagnostic message in SSE and HTTP errors",
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
