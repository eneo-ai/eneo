import { describe, expect, it } from "vitest";
import { failureFacts } from "./run-failure-facts";

describe("failureFacts", () => {
  it("says where a timed-out step stopped, what it was doing and how far it got", () => {
    expect(
      failureFacts({
        step_order: 2,
        retryable: true,
        details: {
          step_description: " Sammanfatta ",
          phase: "mapped_item",
          completed_items: 3,
          total_items: 8,
          provider_work_may_have_completed: true
        }
      })
    ).toEqual([
      { kind: "stopped_at", order: 2, name: "Sammanfatta" },
      { kind: "phase", phase: "mapped_item" },
      { kind: "progress", completed: 3, total: 8 },
      { kind: "provider_may_have_finished" },
      { kind: "retry", retryable: true }
    ]);
  });

  it("warns that a tool may have acted instead of promising the same error again", () => {
    const facts = failureFacts({
      step_order: null,
      retryable: false,
      details: { tool_call_possible: true, tool_error_text: "Ärendet är låst." }
    });
    expect(facts).toEqual([
      { kind: "tool_may_have_acted" },
      { kind: "tool_said", text: "Ärendet är låst." }
    ]);
  });

  it("keeps to the retry advice when the error carries no facts", () => {
    expect(failureFacts({ step_order: null, retryable: false, details: null })).toEqual([
      { kind: "retry", retryable: false }
    ]);
  });

  it("leaves out progress the error cannot vouch for", () => {
    const facts = failureFacts({
      step_order: null,
      retryable: true,
      details: { completed_items: 2, total_items: 0, transcription_service_reason: "  " }
    });
    expect(facts.map((fact) => fact.kind)).toEqual(["retry"]);
  });
});
