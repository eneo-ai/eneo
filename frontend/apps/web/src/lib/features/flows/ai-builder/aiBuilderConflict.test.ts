import { describe, expect, it } from "vitest";

import { classifyAIBuilderConflict } from "./aiBuilderConflict";
import type { AIBuilderError } from "./protocol";

function makeError(code: string): AIBuilderError {
  return {
    schema_version: 2,
    code,
    category: "conflict",
    message: "Conflict",
    phase: "router",
    request_id: null,
    eneo_error_code: null,
    diagnostic_context: null,
    details: {}
  };
}

describe("classifyAIBuilderConflict", () => {
  it("reports no conflict for an ordinary failure", () => {
    expect(
      classifyAIBuilderConflict({
        applyError: makeError("planner_stream_failed"),
        error: null,
        isConflict: false
      })
    ).toBeNull();
  });

  it.each([
    ["stale_revision", "stale_revision"],
    ["stale_plan_revision", "stale_plan"],
    ["session_latest_plan_update_conflict", "stale_plan"],
    ["session_send_in_progress", "send_in_progress"],
    ["session_send_lease_lost", "send_in_progress"],
    ["session_message_in_progress", "send_in_progress"],
    ["session_turn_idempotency_conflict", "send_in_progress"]
  ] as const)("classifies %s as %s", (code, kind) => {
    expect(
      classifyAIBuilderConflict({ applyError: makeError(code), error: null, isConflict: false })
    ).toEqual({ kind });
  });

  it("classifies a conflict that arrived on the stream instead of the apply call", () => {
    // stale_plan_revision is raised inside the turn and reaches the client as
    // an SSE error frame, so it never touches applyError.
    expect(
      classifyAIBuilderConflict({
        applyError: null,
        error: makeError("stale_plan_revision"),
        isConflict: false
      })
    ).toEqual({ kind: "stale_plan" });
  });

  it("falls back to the driver's stale-apply latch", () => {
    expect(classifyAIBuilderConflict({ applyError: null, error: null, isConflict: true })).toEqual({
      kind: "stale_revision"
    });
  });

  it("prefers the apply error over a stream error", () => {
    expect(
      classifyAIBuilderConflict({
        applyError: makeError("stale_revision"),
        error: makeError("session_send_in_progress"),
        isConflict: true
      })
    ).toEqual({ kind: "stale_revision" });
  });
});
