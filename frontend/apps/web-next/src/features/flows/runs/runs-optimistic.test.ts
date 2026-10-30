import { describe, expect, it } from "vitest";
import { testQueryClient } from "@/test/render";
import { makeRunDetail, makeRunSummary } from "./run-fixtures";
import {
  rememberStartedRun,
  runSummaryOf,
  startedRunsKey,
  withStartedRuns,
  type StartedRun
} from "./runs-optimistic";
import type { RunStatusCounts } from "./runs-api";

const COUNTS: RunStatusCounts = {
  queued: 0,
  running: 1,
  awaiting_review: 0,
  completed: 4,
  failed: 0,
  cancelled: 0
};
const LISTED_AT = Date.parse("2026-10-21T08:00:00Z");
const NEWEST_FIRST = { mine: false, sort: { key: "started_at", order: "desc" } } as const;

function started(id: string, at: number): StartedRun {
  return {
    run: makeRunSummary({ id, status: "queued", started_at: null, finished_at: null }),
    startedAt: at
  };
}

describe("runSummaryOf", () => {
  it("keeps the run's summary and leaves its input and result out", () => {
    const summary = runSummaryOf(
      makeRunDetail({ id: "run-5", run_label: "Ärende 5", input_payload_json: { a: "b" } })
    );
    expect(summary).toMatchObject({ id: "run-5", run_label: "Ärende 5", status: "completed" });
    expect(summary).not.toHaveProperty("input_payload_json");
    expect(summary).not.toHaveProperty("result");
    expect(summary).not.toHaveProperty("token_usage");
  });
});

describe("withStartedRuns", () => {
  const listed = [makeRunSummary({ id: "run-1" })];

  it("shows a run started after the list's answer first, counted in its status", () => {
    const shown = withStartedRuns(
      listed,
      COUNTS,
      [started("run-9", LISTED_AT + 1)],
      NEWEST_FIRST,
      LISTED_AT
    );
    expect(shown.items.map((run) => run.id)).toEqual(["run-9", "run-1"]);
    expect(shown.counts).toEqual({ ...COUNTS, queued: 1 });
  });

  it("leaves out a run the list reports or that started before its answer", () => {
    const listedToo = [makeRunSummary({ id: "run-9" }), ...listed];
    expect(
      withStartedRuns(listedToo, COUNTS, [started("run-9", LISTED_AT + 1)], NEWEST_FIRST, LISTED_AT)
        .items
    ).toEqual(listedToo);
    expect(
      withStartedRuns(listed, COUNTS, [started("run-9", LISTED_AT - 1)], NEWEST_FIRST, LISTED_AT)
    ).toEqual({ items: listed, counts: COUNTS });
  });

  it("leaves it out of a search, another status and another order", () => {
    const run = [started("run-9", LISTED_AT + 1)];
    for (const filter of [
      { mine: false, search: "ärende" },
      { mine: false, status: "completed" as const },
      { mine: true, sort: { key: "duration", order: "desc" } as const }
    ]) {
      expect(withStartedRuns(listed, COUNTS, run, filter, LISTED_AT).items).toEqual(listed);
    }
    expect(
      withStartedRuns(listed, COUNTS, run, { mine: true, status: "queued" }, LISTED_AT).items
    ).toHaveLength(2);
  });
});

describe("rememberStartedRun", () => {
  it("keeps the runs newest first, one entry per run", () => {
    const queryClient = testQueryClient();
    rememberStartedRun(queryClient, "flow-1", makeRunDetail({ id: "run-1" }), 1);
    rememberStartedRun(queryClient, "flow-1", makeRunDetail({ id: "run-2" }), 2);
    rememberStartedRun(queryClient, "flow-1", makeRunDetail({ id: "run-1" }), 3);
    const remembered = queryClient.getQueryData<StartedRun[]>(startedRunsKey("flow-1"));
    expect(remembered?.map((item) => [item.run.id, item.startedAt])).toEqual([
      ["run-1", 3],
      ["run-2", 2]
    ]);
  });
});
