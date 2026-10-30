import { describe, expect, it } from "vitest";
import {
  canRedispatch,
  createPollClock,
  isCancellable,
  listNeedsPolling,
  listSignature,
  pollDelayMs,
  runDurationMs,
  runElapsedMs,
  runStatusView,
  shouldPoll,
  statusChanges,
  stepStatusView
} from "./run-status";
import { makeRunSummary } from "./run-fixtures";

describe("the core's status table", () => {
  it("polls what moves or waits for review, and stops at the end", () => {
    expect(["queued", "running", "awaiting_review"].every(shouldPoll)).toBe(true);
    expect(["completed", "failed", "cancelled"].some(shouldPoll)).toBe(false);
  });

  it("offers cancel until the run has ended", () => {
    expect(isCancellable("awaiting_review")).toBe(true);
    expect(isCancellable("failed")).toBe(false);
  });

  it("treats a status it does not know as settled", () => {
    expect(shouldPoll("paused")).toBe(false);
    expect(isCancellable("paused")).toBe(false);
    expect(runStatusView("paused").labelKey).toBe("flow_runs_status_unknown");
  });
});

describe("canRedispatch", () => {
  const now = Date.parse("2026-10-21T08:10:00Z");

  it("offers it for a queued run whose dispatch is due or gave up", () => {
    expect(
      canRedispatch(
        makeRunSummary({ status: "queued", dispatch_next_attempt_at: "2026-10-21T08:09:00Z" }),
        now
      )
    ).toBe(true);
    expect(
      canRedispatch(
        makeRunSummary({ status: "queued", dispatch_exhausted_at: "2026-10-21T08:00:00Z" }),
        now
      )
    ).toBe(true);
  });

  it("does not offer it before the server's clock is due, or for other statuses", () => {
    expect(
      canRedispatch(
        makeRunSummary({ status: "queued", dispatch_next_attempt_at: "2026-10-21T08:11:00Z" }),
        now
      )
    ).toBe(false);
    expect(
      canRedispatch(
        makeRunSummary({ status: "running", dispatch_exhausted_at: "2026-10-21T08:00:00Z" }),
        now
      )
    ).toBe(false);
  });
});

describe("polling", () => {
  it("follows the API's cadence from the last change seen", () => {
    expect(pollDelayMs(0)).toBe(2_000);
    expect(pollDelayMs(29_999)).toBe(2_000);
    expect(pollDelayMs(30_000)).toBe(5_000);
    expect(pollDelayMs(10 * 60_000)).toBe(15_000);
  });

  it("polls the list only while a run in it can still change", () => {
    expect(listNeedsPolling([makeRunSummary({ status: "completed" })])).toBe(false);
    expect(
      listNeedsPolling([
        makeRunSummary({ status: "completed" }),
        makeRunSummary({ status: "awaiting_review" })
      ])
    ).toBe(true);
  });

  it("sees a change when a run's status or revision moves", () => {
    const before = [makeRunSummary({ status: "running", revision: 2 })];
    expect(listSignature(before)).toBe(listSignature([...before]));
    expect(listSignature(before)).not.toBe(
      listSignature([makeRunSummary({ status: "running", revision: 3 })])
    );
  });
});

describe("presentation", () => {
  it("gives every status its own text", () => {
    expect(runStatusView("failed")).toEqual({
      tone: "error",
      labelKey: "flow_runs_status_failed",
      isPulsing: false
    });
    expect(stepStatusView("running").isPulsing).toBe(true);
    expect(stepStatusView(null).labelKey).toBe("flow_runs_status_unknown");
  });

  it("measures a finished run from when it started", () => {
    expect(runDurationMs(makeRunSummary())).toBe(65_000);
    expect(runDurationMs(makeRunSummary({ finished_at: null }))).toBeNull();
  });

  it("measures a run still going up to now, and an ended one not at all", () => {
    const now = Date.parse("2026-10-21T08:01:00Z");
    const running = makeRunSummary({ status: "running", finished_at: null });
    expect(runElapsedMs(running, now)).toBe(58_000);
    const queued = makeRunSummary({ status: "queued", started_at: null, finished_at: null });
    expect(runElapsedMs(queued, now)).toBe(60_000);
    expect(runElapsedMs(makeRunSummary(), now)).toBeNull();
  });
});

describe("statusChanges", () => {
  it("names the runs whose status moved, not the ones it has not seen", () => {
    const previous = new Map([
      ["run-1", "running"],
      ["run-2", "queued"]
    ]);
    const runs = [
      makeRunSummary({ id: "run-3", status: "running" }),
      makeRunSummary({ id: "run-1", status: "completed" }),
      makeRunSummary({ id: "run-2", status: "queued" })
    ];
    expect(statusChanges(previous, runs).map((run) => run.id)).toEqual(["run-1"]);
  });
});

describe("createPollClock", () => {
  it("polls closely after a change and backs off while nothing moves", () => {
    let now = 0;
    const clock = createPollClock(() => now);
    expect(clock("a", true)).toBe(2_000);
    now = 40_000;
    expect(clock("a", true)).toBe(5_000);
    expect(clock("b", true)).toBe(2_000);
    now = 400_000;
    expect(clock("b", true)).toBe(15_000);
  });

  it("stops when nothing needs polling", () => {
    expect(createPollClock(() => 0)("a", false)).toBe(false);
  });
});
