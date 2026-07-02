import type { FlowRun } from "@eneo/eneo-js";
import { describe, expect, it } from "vitest";
import {
  DEFAULT_FLOW_RUN_HISTORY_SORT,
  createFlowRunStatusCounts,
  getFlowRunDurationMs,
  getFlowRunHistoryAriaSort,
  getVisibleFlowRuns,
  nextFlowRunHistorySortState
} from "./flowRunHistoryPresentation";
import { FLOW_RUN_STATUS_VALUES } from "./flowRunStatusSets";

function run(
  id: string,
  overrides: Partial<FlowRun> & Pick<FlowRun, "status"> = { status: "completed" }
): FlowRun {
  const { status, ...rest } = overrides;
  return {
    id,
    status,
    created_at: "2026-05-14T10:00:00.000Z",
    started_at: "2026-05-14T10:00:00.000Z",
    finished_at: "2026-05-14T10:01:00.000Z",
    ...rest
  } as FlowRun;
}

describe("createFlowRunStatusCounts", () => {
  it("returns zero for every known status before counting runs", () => {
    const counts = createFlowRunStatusCounts([]);

    expect(Object.keys(counts).sort()).toEqual([...FLOW_RUN_STATUS_VALUES].sort());
    for (const status of FLOW_RUN_STATUS_VALUES) {
      expect(counts[status]).toBe(0);
    }
  });

  it("counts matching statuses", () => {
    const counts = createFlowRunStatusCounts([
      run("a", { status: "completed" }),
      run("b", { status: "failed" }),
      run("c", { status: "completed" })
    ]);

    expect(counts.completed).toBe(2);
    expect(counts.failed).toBe(1);
    expect(counts.running).toBe(0);
  });
});

describe("getFlowRunDurationMs", () => {
  it("returns null when timestamps are missing or invalid", () => {
    expect(getFlowRunDurationMs(run("missing", { status: "completed", finished_at: null }))).toBe(
      null
    );
    expect(
      getFlowRunDurationMs(
        run("invalid", {
          status: "completed",
          started_at: "not-a-date",
          finished_at: "2026-05-14T10:01:00.000Z"
        })
      )
    ).toBe(null);
  });

  it("uses started_at before created_at", () => {
    expect(
      getFlowRunDurationMs(
        run("duration", {
          status: "completed",
          created_at: "2026-05-14T09:00:00.000Z",
          started_at: "2026-05-14T10:00:00.000Z",
          finished_at: "2026-05-14T10:02:00.000Z"
        })
      )
    ).toBe(120_000);
  });
});

describe("getVisibleFlowRuns", () => {
  const runs = [
    run("run-c", {
      status: "running",
      started_at: "2026-05-14T10:03:00.000Z",
      finished_at: null
    }),
    run("run-a", {
      status: "completed",
      started_at: "2026-05-14T10:01:00.000Z",
      finished_at: "2026-05-14T10:03:00.000Z"
    }),
    run("run-b", {
      status: "failed",
      started_at: "2026-05-14T10:02:00.000Z",
      finished_at: "2026-05-14T10:02:30.000Z"
    })
  ];

  it("keeps all runs when status filter is null", () => {
    expect(
      getVisibleFlowRuns(runs, {
        statusFilter: null,
        sortState: { key: "started", dir: "asc" }
      }).map((item) => item.id)
    ).toEqual(["run-a", "run-b", "run-c"]);
  });

  it("filters by status before sorting", () => {
    expect(
      getVisibleFlowRuns(runs, {
        statusFilter: "completed",
        sortState: DEFAULT_FLOW_RUN_HISTORY_SORT
      }).map((item) => item.id)
    ).toEqual(["run-a"]);
  });

  it("sorts by started time, duration, and status in both directions", () => {
    expect(
      getVisibleFlowRuns(runs, {
        statusFilter: null,
        sortState: { key: "started", dir: "asc" }
      }).map((item) => item.id)
    ).toEqual(["run-a", "run-b", "run-c"]);
    expect(
      getVisibleFlowRuns(runs, {
        statusFilter: null,
        sortState: { key: "started", dir: "desc" }
      }).map((item) => item.id)
    ).toEqual(["run-c", "run-b", "run-a"]);

    expect(
      getVisibleFlowRuns(runs, {
        statusFilter: null,
        sortState: { key: "duration", dir: "asc" }
      }).map((item) => item.id)
    ).toEqual(["run-c", "run-b", "run-a"]);
    expect(
      getVisibleFlowRuns(runs, {
        statusFilter: null,
        sortState: { key: "duration", dir: "desc" }
      }).map((item) => item.id)
    ).toEqual(["run-a", "run-b", "run-c"]);

    expect(
      getVisibleFlowRuns(runs, {
        statusFilter: null,
        sortState: { key: "status", dir: "asc" }
      }).map((item) => item.status)
    ).toEqual(["completed", "failed", "running"]);
    expect(
      getVisibleFlowRuns(runs, {
        statusFilter: null,
        sortState: { key: "status", dir: "desc" }
      }).map((item) => item.status)
    ).toEqual(["running", "failed", "completed"]);
  });

  it("tie-breaks equal primary sort keys by run id", () => {
    const tied = [
      run("b-run", { status: "completed", started_at: "2026-05-14T10:00:00.000Z" }),
      run("a-run", { status: "completed", started_at: "2026-05-14T10:00:00.000Z" })
    ];

    expect(
      getVisibleFlowRuns(tied, {
        statusFilter: null,
        sortState: { key: "started", dir: "asc" }
      }).map((item) => item.id)
    ).toEqual(["a-run", "b-run"]);
  });
});

describe("sort state helpers", () => {
  it("toggles existing sort direction and chooses default direction for new keys", () => {
    expect(nextFlowRunHistorySortState({ key: "started", dir: "desc" }, "started")).toEqual({
      key: "started",
      dir: "asc"
    });
    expect(nextFlowRunHistorySortState({ key: "started", dir: "asc" }, "status")).toEqual({
      key: "status",
      dir: "asc"
    });
    expect(nextFlowRunHistorySortState({ key: "status", dir: "asc" }, "duration")).toEqual({
      key: "duration",
      dir: "desc"
    });
  });

  it("returns ARIA sort state for the active column only", () => {
    expect(getFlowRunHistoryAriaSort({ key: "duration", dir: "desc" }, "duration")).toBe(
      "descending"
    );
    expect(getFlowRunHistoryAriaSort({ key: "duration", dir: "desc" }, "started")).toBe("none");
  });
});
