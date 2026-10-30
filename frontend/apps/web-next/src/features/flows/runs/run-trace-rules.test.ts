import { describe, expect, it } from "vitest";
import { EneoApiError } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import {
  attemptDurationMs,
  attemptsByStep,
  exportRecovery,
  rawReasonProblem
} from "./run-trace-rules";

function attempt(step_order: number, attempt_no: number) {
  return {
    id: `attempt-${step_order}-${attempt_no}`,
    step_order,
    attempt_no,
    started_at: "2026-10-21T08:00:00Z",
    finished_at: "2026-10-21T08:00:12Z"
  } as Schema<"FlowStepAttemptPublic">;
}

describe("rawReasonProblem", () => {
  it("asks for a reason of the person's own", () => {
    expect(rawReasonProblem("  ")).toBe("required");
    expect(rawReasonProblem("ab")).toBe("required");
    expect(rawReasonProblem(" support_debug ")).toBe("required");
    expect(rawReasonProblem("Begäran om allmän handling")).toBeNull();
    expect(rawReasonProblem("x".repeat(501))).toBe("too_long");
  });
});

describe("exportRecovery", () => {
  const tooLarge = (limit: string) =>
    new EneoApiError("too large", {
      status: 413,
      reason: "flow_evidence_export_too_large",
      context: { limit }
    });

  it("points an oversized export to where the evidence can be read", () => {
    expect(exportRecovery(tooLarge("recorded_passage_bytes"))).toBe("trace");
    expect(exportRecovery(tooLarge("provider_call_events"))).toBe("provider_calls");
    expect(exportRecovery(tooLarge("section_rows"))).toBe("generic");
  });

  it("has nothing to add for other refusals", () => {
    expect(
      exportRecovery(
        new EneoApiError("off", { status: 403, reason: "flow_run_evidence_export_disabled" })
      )
    ).toBeNull();
    expect(exportRecovery(new Error("network"))).toBeNull();
  });
});

describe("attemptsByStep", () => {
  it("groups attempts by step, each step's in order", () => {
    const grouped = attemptsByStep([attempt(2, 2), attempt(1, 1), attempt(2, 1)]);
    expect([...grouped.keys()]).toEqual([1, 2]);
    expect(grouped.get(2)?.map((item) => item.attempt_no)).toEqual([1, 2]);
  });

  it("measures a finished attempt only", () => {
    expect(attemptDurationMs(attempt(1, 1))).toBe(12_000);
    expect(attemptDurationMs({ ...attempt(1, 1), finished_at: null })).toBeNull();
  });
});
