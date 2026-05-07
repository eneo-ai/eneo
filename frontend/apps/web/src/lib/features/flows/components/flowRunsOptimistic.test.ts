import type { FlowRun } from "@intric/intric-js";
import { describe, expect, it } from "vitest";

import {
  getConfirmedOptimisticFlowRunIds,
  mergeOptimisticFlowRuns,
  shouldAutoFocusOptimisticFlowRun
} from "./flowRunsOptimistic";

function run(id: string): FlowRun {
  return {
    id,
    flow_id: "flow-1",
    flow_version: 1,
    tenant_id: "tenant-1",
    trace_id: `trace-${id}`,
    revision: 1,
    status: "running",
    created_at: "2026-05-07T12:00:00.000Z",
    updated_at: "2026-05-07T12:00:00.000Z"
  };
}

describe("mergeOptimisticFlowRuns", () => {
  it("keeps a newly created run visible while the backend list is stale", () => {
    expect(mergeOptimisticFlowRuns([], [run("run-new")]).map((item) => item.id)).toEqual([
      "run-new"
    ]);
  });

  it("does not duplicate a run once the backend list includes it", () => {
    expect(
      mergeOptimisticFlowRuns([run("run-new"), run("run-old")], [run("run-new")]).map(
        (item) => item.id
      )
    ).toEqual(["run-new", "run-old"]);
  });

  it("preserves multiple optimistic runs until each appears in the backend list", () => {
    expect(
      mergeOptimisticFlowRuns([run("run-old")], [run("run-b"), run("run-a")]).map((item) => item.id)
    ).toEqual(["run-b", "run-a", "run-old"]);
  });

  it("reports optimistic runs confirmed by the backend list", () => {
    expect(
      getConfirmedOptimisticFlowRunIds([run("run-b"), run("run-old")], [run("run-b"), run("run-a")])
    ).toEqual(["run-b"]);
  });

  it("auto-focuses an optimistic run only once so polling does not steal manual selection", () => {
    expect(shouldAutoFocusOptimisticFlowRun(run("run-new"), null)).toBe(true);
    expect(shouldAutoFocusOptimisticFlowRun(run("run-new"), "run-new")).toBe(false);
  });
});
