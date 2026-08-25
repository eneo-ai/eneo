import type { FlowRun } from "@eneo/eneo-js";
import { describe, expect, it } from "vitest";
import {
  DEFAULT_FLOW_RUN_HISTORY_SORT,
  createFlowRunStatusCounts,
  filterFlowRuns,
  getFlowRunDurationMs,
  getFlowRunHistoryAriaSort,
  nextFlowRunHistorySortState,
  sortFlowRuns,
  type FlowRunHistorySortState,
  type FlowRunSearchLabels
} from "./flowRunHistoryPresentation";
import type { FlowRunStatusFilter } from "./flowRunStatusSets";
import { FLOW_RUN_STATUS_VALUES } from "./flowRunStatusSets";
import { makeFlowRun, makeFlowRunResultFile } from "./flowRunHistoryTestFixtures";

const PLAIN_LABELS: FlowRunSearchLabels = {
  labelsKey: "test",
  getStatusLabel: (status) => status,
  getDateLabel: () => ""
};

function visible(
  runs: FlowRun[],
  options: {
    statusFilter: FlowRunStatusFilter;
    sortState: FlowRunHistorySortState;
    searchQuery?: string;
    labels?: FlowRunSearchLabels;
  }
): FlowRun[] {
  return filterFlowRuns(sortFlowRuns(runs, options.sortState), {
    statusFilter: options.statusFilter,
    searchQuery: options.searchQuery,
    labels: options.labels ?? PLAIN_LABELS
  });
}

function run(
  id: string,
  overrides: Partial<FlowRun> & Pick<FlowRun, "status"> = { status: "completed" }
): FlowRun {
  return makeFlowRun({
    id,
    created_at: "2026-05-14T10:00:00.000Z",
    started_at: "2026-05-14T10:00:00.000Z",
    finished_at: "2026-05-14T10:01:00.000Z",
    ...overrides
  });
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

describe("sorted and filtered projection", () => {
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
      visible(runs, {
        statusFilter: null,
        sortState: { key: "started", dir: "asc" }
      }).map((item) => item.id)
    ).toEqual(["run-a", "run-b", "run-c"]);
  });

  it("filters by status before sorting", () => {
    expect(
      visible(runs, {
        statusFilter: "completed",
        sortState: DEFAULT_FLOW_RUN_HISTORY_SORT
      }).map((item) => item.id)
    ).toEqual(["run-a"]);
  });

  it("sorts by started time, duration, and status in both directions", () => {
    expect(
      visible(runs, {
        statusFilter: null,
        sortState: { key: "started", dir: "asc" }
      }).map((item) => item.id)
    ).toEqual(["run-a", "run-b", "run-c"]);
    expect(
      visible(runs, {
        statusFilter: null,
        sortState: { key: "started", dir: "desc" }
      }).map((item) => item.id)
    ).toEqual(["run-c", "run-b", "run-a"]);

    expect(
      visible(runs, {
        statusFilter: null,
        sortState: { key: "duration", dir: "asc" }
      }).map((item) => item.id)
    ).toEqual(["run-c", "run-b", "run-a"]);
    expect(
      visible(runs, {
        statusFilter: null,
        sortState: { key: "duration", dir: "desc" }
      }).map((item) => item.id)
    ).toEqual(["run-a", "run-b", "run-c"]);

    expect(
      visible(runs, {
        statusFilter: null,
        sortState: { key: "status", dir: "asc" }
      }).map((item) => item.status)
    ).toEqual(["completed", "failed", "running"]);
    expect(
      visible(runs, {
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
      visible(tied, {
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

describe("search projection", () => {
  const searchRun = (id: string, status: FlowRun["status"], created: string): FlowRun =>
    makeFlowRun({
      id,
      status,
      created_at: created,
      flow_version: 3,
      input_payload_json: { arende: "Bygglov Storgatan 5" }
    });

  const swedishLabels: FlowRunSearchLabels = {
    labelsKey: "sv",
    getStatusLabel: (status) => (status === "completed" ? "Klar" : status),
    getDateLabel: () => ""
  };

  const options = {
    statusFilter: null,
    sortState: DEFAULT_FLOW_RUN_HISTORY_SORT,
    labels: swedishLabels
  };

  it("matches on run id, date, status label and input content", () => {
    const runs = [
      searchRun("a1b2", "completed", "2026-08-25T09:00:00Z"),
      searchRun("c3d4", "failed", "2026-08-24T09:00:00Z")
    ];
    expect(visible(runs, { ...options, searchQuery: "a1b2" })).toHaveLength(1);
    expect(visible(runs, { ...options, searchQuery: "2026-08-24" })).toHaveLength(1);
    expect(visible(runs, { ...options, searchQuery: "klar" })).toHaveLength(1);
    expect(visible(runs, { ...options, searchQuery: "storgatan" })).toHaveLength(2);
    expect(visible(runs, { ...options, searchQuery: "finns-inte" })).toHaveLength(0);
  });

  it("matches on result file names", () => {
    const withFile = makeFlowRun({
      id: "a1b2",
      result_files: [makeFlowRunResultFile({ name: "beslut_bygglov.docx" })]
    });
    const runs = [withFile, searchRun("c3d4", "failed", "2026-08-24T09:00:00Z")];
    expect(visible(runs, { ...options, searchQuery: "beslut_bygglov" })).toHaveLength(1);
    expect(visible(runs, { ...options, searchQuery: ".docx" })).toHaveLength(1);
  });

  it("matches on the displayed date label", () => {
    const runs = [searchRun("a1b2", "completed", "2026-08-25T09:00:00Z")];
    const labels: FlowRunSearchLabels = {
      ...swedishLabels,
      getDateLabel: () => "25 augusti 2026 11:00"
    };
    expect(visible(runs, { ...options, labels, searchQuery: "25 augusti" })).toHaveLength(1);
  });

  it("runs input reads and label formatting once per run per label set", () => {
    let inputReads = 0;
    let dateLabelCalls = 0;
    const target = makeFlowRun({
      id: "a1b2",
      input_payload_json: {
        get arende() {
          inputReads += 1;
          return "Bygglov Storgatan 5";
        }
      } as FlowRun["input_payload_json"]
    });
    const runs = [target];
    const countingLabels: FlowRunSearchLabels = {
      labelsKey: "sv",
      getStatusLabel: (status) => (status === "completed" ? "Klar" : status),
      getDateLabel: () => {
        dateLabelCalls += 1;
        return "25 augusti 2026 11:00";
      }
    };

    expect(
      visible(runs, { ...options, labels: countingLabels, searchQuery: "storgatan" })
    ).toHaveLength(1);
    expect(visible(runs, { ...options, labels: countingLabels, searchQuery: "klar" })).toHaveLength(
      1
    );
    expect(
      visible(runs, { ...options, labels: countingLabels, searchQuery: "finns-inte" })
    ).toHaveLength(0);
    // The label callbacks and input reads ran only on the first miss.
    expect(inputReads).toBe(1);
    expect(dateLabelCalls).toBe(1);

    const englishLabels: FlowRunSearchLabels = {
      ...countingLabels,
      labelsKey: "en",
      getStatusLabel: (status) => (status === "completed" ? "Done" : status)
    };
    expect(visible(runs, { ...options, labels: englishLabels, searchQuery: "done" })).toHaveLength(
      1
    );
    expect(visible(runs, { ...options, labels: englishLabels, searchQuery: "klar" })).toHaveLength(
      0
    );
    // The input text is payload-keyed and survives a label-set switch;
    // only the label-derived parts rebuild.
    expect(inputReads).toBe(1);
    expect(dateLabelCalls).toBe(2);
  });

  it("matches multiselect array values in the input", () => {
    const runs = [
      makeFlowRun({
        id: "a1b2",
        input_payload_json: { verksamheter: ["Skola", "Äldreomsorg"], antal: 3 }
      })
    ];
    expect(visible(runs, { ...options, searchQuery: "äldreomsorg" })).toHaveLength(1);
    expect(visible(runs, { ...options, searchQuery: "skola" })).toHaveLength(1);
  });

  it("bounds search-text build cost and size for hostile payloads", () => {
    const huge = "x".repeat(1_000_000) + "SLUTMARKÖR";
    const manyKeys = Object.fromEntries(
      Array.from({ length: 50_000 }, (_, i) => [`nyckel_${i}`, `värde_${i}`])
    );
    const runs = [
      makeFlowRun({ id: "big-string", input_payload_json: { text: huge } }),
      makeFlowRun({ id: "many-keys", input_payload_json: manyKeys })
    ];
    const t0 = performance.now();
    // The tail of a megabyte value is beyond the per-value budget: honest
    // truncation, not silent full-payload search.
    expect(visible(runs, { ...options, searchQuery: "slutmarkör" })).toHaveLength(0);
    expect(visible(runs, { ...options, searchQuery: "nyckel_49999" })).toHaveLength(0);
    // Values within the budget match.
    expect(visible(runs, { ...options, searchQuery: "nyckel_1" })).toHaveLength(1);
    expect(performance.now() - t0).toBeLessThan(500);
  });

  it("combines search with the status filter", () => {
    const runs = [
      searchRun("a1b2", "completed", "2026-08-25T09:00:00Z"),
      searchRun("c3d4", "failed", "2026-08-25T10:00:00Z")
    ];
    expect(
      visible(runs, {
        ...options,
        statusFilter: "failed",
        searchQuery: "2026-08-25"
      })
    ).toHaveLength(1);
  });
});
