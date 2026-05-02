import { describe, expect, test } from "vitest";

import { getActiveFlowRunId, shouldAutoFocusFlowRun } from "./flowRunsFocus";

describe("flowRunsFocus helpers", () => {
  test("selects the first queued or running run", () => {
    expect(
      getActiveFlowRunId([
        { id: "completed", status: "completed" },
        { id: "running", status: "running" },
        { id: "queued", status: "queued" }
      ])
    ).toBe("running");
  });

  test("does not treat awaiting review as an active run", () => {
    expect(
      getActiveFlowRunId([
        { id: "review", status: "awaiting_review" },
        { id: "completed", status: "completed" }
      ])
    ).toBeNull();
  });

  test("auto-focuses an active run when no run is selected", () => {
    expect(
      shouldAutoFocusFlowRun({
        runs: [{ id: "running", status: "running" }],
        activeRunId: "running",
        selectedRunId: null,
        lastAutoFocusedRunId: null
      })
    ).toBe(true);
  });

  test("keeps following the previously auto-focused active run", () => {
    expect(
      shouldAutoFocusFlowRun({
        runs: [
          { id: "old", status: "completed" },
          { id: "new", status: "running" }
        ],
        activeRunId: "new",
        selectedRunId: "old",
        lastAutoFocusedRunId: "old"
      })
    ).toBe(true);
  });

  test("does not steal focus from a manually selected active run", () => {
    expect(
      shouldAutoFocusFlowRun({
        runs: [
          { id: "selected", status: "running" },
          { id: "new", status: "queued" }
        ],
        activeRunId: "new",
        selectedRunId: "selected",
        lastAutoFocusedRunId: null
      })
    ).toBe(false);
  });
});
