import { describe, expect, it } from "vitest";
import { runActions } from "./run-actions";
import { makeRunSummary } from "./run-fixtures";

const person = { canRun: true, userId: "user-1", publishedVersion: 3 };
const failed = makeRunSummary({ status: "failed", flow_version: 3 });
const firstDone = [
  { order: 1, status: "completed" },
  { order: 2, status: "failed" }
];
const firstFailed = [
  { order: 1, status: "failed" },
  { order: 2, status: null }
];

describe("runActions", () => {
  it("offers a retry only when the core has a completed first step to reuse", () => {
    expect(runActions(failed, person, { steps: firstDone })).toMatchObject({
      retry: true,
      newRun: true,
      primary: "retry"
    });
    expect(runActions(failed, person, { steps: firstFailed })).toMatchObject({
      retry: false,
      heldBack: null,
      newRun: true,
      primary: "new_run"
    });
    // The runs list has no step data: the run's page decides.
    expect(runActions(failed, person, null).retry).toBe(false);
  });

  it("leads with the retry whatever the error's code: `retryable` does not say the same error comes back", () => {
    expect(runActions(failed, person, { steps: firstDone })).toMatchObject({
      retry: true,
      newRun: true,
      primary: "retry"
    });
  });

  it("offers a new run of a cancelled run, and nothing to run again while the flow is unpublished", () => {
    const cancelled = makeRunSummary({ status: "cancelled", flow_version: 3 });
    expect(runActions(cancelled, person, { steps: firstDone })).toMatchObject({
      retry: false,
      newRun: true,
      cancel: false,
      primary: "new_run"
    });
    for (const run of [cancelled, failed]) {
      expect(
        runActions(run, { ...person, publishedVersion: null }, { steps: firstDone })
      ).toMatchObject({ retry: false, newRun: false, heldBack: "unpublished", primary: null });
    }
  });

  it("says a run of an earlier version cannot be retried, and still offers a new run", () => {
    const earlier = makeRunSummary({ status: "failed", flow_version: 2 });
    expect(runActions(earlier, person, { steps: firstDone })).toMatchObject({
      retry: false,
      heldBack: "version_changed",
      newRun: true,
      primary: "new_run"
    });
  });

  it("offers nothing to someone who may not run the flow", () => {
    expect(runActions(failed, { ...person, canRun: false }, { steps: firstDone })).toMatchObject({
      retry: false,
      newRun: false,
      heldBack: null,
      primary: null
    });
  });
});
