import type { FlowRun } from "@eneo/eneo-js";
import { describe, expect, it } from "vitest";
import {
  createFlowRunHistoryState,
  destroyFlowRunHistoryPolling,
  type FlowRunHistoryPollTimeout,
  loadFlowRunHistory,
  syncFlowRunHistoryFlow,
  syncFlowRunHistoryPolling,
  syncFlowRunHistoryReload
} from "./flowRunHistoryState";

function run(id: string, status: FlowRun["status"] = "completed"): FlowRun {
  return { id, status } as FlowRun;
}

describe("loadFlowRunHistory", () => {
  it("loads runs and normalizes paginated API results", async () => {
    const state = createFlowRunHistoryState();

    const result = await loadFlowRunHistory(state, {
      flowId: "flow-1",
      listRuns: async () => ({ items: [run("run-1")] }),
      getErrorMessage: () => "failed"
    });

    expect(result).toEqual({ kind: "loaded", runs: [run("run-1")] });
    expect(state.runs.map((item) => item.id)).toEqual(["run-1"]);
    expect(state.loading).toBe(false);
    expect(state.loadError).toBeNull();
    expect(state.isInitialLoad).toBe(false);
    expect(state.loadInFlight).toBe(false);
  });

  it("clears runs when no flow is selected", async () => {
    const state = createFlowRunHistoryState();
    state.runs = [run("old-run")];

    const result = await loadFlowRunHistory(state, {
      flowId: null,
      listRuns: async () => [run("should-not-load")],
      getErrorMessage: () => "failed"
    });

    expect(result).toEqual({ kind: "no_flow" });
    expect(state.runs).toEqual([]);
    expect(state.loading).toBe(false);
  });

  it("stores a formatted load error and resets the in-flight flag", async () => {
    const state = createFlowRunHistoryState();

    const result = await loadFlowRunHistory(state, {
      flowId: "flow-1",
      listRuns: async () => {
        throw new Error("backend failed");
      },
      getErrorMessage: (error) => (error instanceof Error ? error.message : "failed")
    });

    if (result.kind !== "failed") {
      throw new Error(`Expected failed result, received ${result.kind}`);
    }
    expect(result.message).toBe("backend failed");
    expect(state.loadError).toBe("backend failed");
    expect(state.loading).toBe(false);
    expect(state.loadInFlight).toBe(false);
  });

  it("does not start a second load while one is already running", async () => {
    const state = createFlowRunHistoryState();
    state.loadInFlight = true;

    const result = await loadFlowRunHistory(state, {
      flowId: "flow-1",
      listRuns: async () => [run("should-not-load")],
      getErrorMessage: () => "failed"
    });

    expect(result).toEqual({ kind: "already_loading" });
  });
});

describe("syncFlowRunHistoryFlow", () => {
  it("requests a load when the flow id changes", () => {
    const state = createFlowRunHistoryState();

    expect(syncFlowRunHistoryFlow(state, "flow-1")).toBe(true);
    expect(state.lastLoadedFlowId).toBe("flow-1");
    expect(state.isInitialLoad).toBe(true);
    expect(syncFlowRunHistoryFlow(state, "flow-1")).toBe(false);
  });

  it("clears stale runs when there is no flow id", () => {
    const state = createFlowRunHistoryState();
    state.lastLoadedFlowId = "flow-1";
    state.runs = [run("run-1")];
    state.loading = true;

    expect(syncFlowRunHistoryFlow(state, null)).toBe(false);
    expect(state.lastLoadedFlowId).toBeNull();
    expect(state.runs).toEqual([]);
    expect(state.loading).toBe(false);
  });
});

describe("syncFlowRunHistoryReload", () => {
  it("reloads only when the trigger moves forward", () => {
    const state = createFlowRunHistoryState();

    expect(syncFlowRunHistoryReload(state, 0)).toBe(false);
    expect(syncFlowRunHistoryReload(state, 1)).toBe(true);
    expect(syncFlowRunHistoryReload(state, 1)).toBe(false);
    expect(syncFlowRunHistoryReload(state, 0)).toBe(false);
    expect(syncFlowRunHistoryReload(state, 2)).toBe(true);
  });
});

describe("syncFlowRunHistoryPolling", () => {
  it("schedules polling while visible runs are active", async () => {
    const state = createFlowRunHistoryState();
    const scheduled: { callback: (() => void | Promise<void>) | null } = { callback: null };
    let loadCount = 0;
    let hasRunsToPoll = true;

    syncFlowRunHistoryPolling(state, {
      visible: () => true,
      hasRunsToPoll: () => hasRunsToPoll,
      loadRuns: async () => {
        loadCount += 1;
        hasRunsToPoll = false;
      },
      setTimeoutFn: (callback) => {
        scheduled.callback = callback;
        return 1;
      }
    });

    expect(state.pollTimeout).not.toBeNull();
    const callback = scheduled.callback;
    if (!callback) {
      throw new Error("Expected polling to schedule a callback");
    }
    await callback();

    expect(loadCount).toBe(1);
    expect(state.pollTimeout).toBeNull();
  });

  it("resets polling timeout even when a future load implementation rejects", async () => {
    const state = createFlowRunHistoryState();
    const scheduled: { callback: (() => void | Promise<void>) | null } = { callback: null };

    syncFlowRunHistoryPolling(state, {
      visible: () => true,
      hasRunsToPoll: () => true,
      loadRuns: async () => {
        throw new Error("future load rejection");
      },
      setTimeoutFn: (callback) => {
        scheduled.callback = callback;
        return 1;
      }
    });

    const callback = scheduled.callback;
    if (!callback) {
      throw new Error("Expected polling to schedule a callback");
    }
    await expect(callback()).rejects.toThrow("future load rejection");

    expect(state.pollTimeout).toBeNull();
  });

  it("clears an existing polling timeout when the history is hidden", () => {
    const state = createFlowRunHistoryState();
    const timeout = 1;
    let clearedTimeout: FlowRunHistoryPollTimeout | null = null;
    state.pollTimeout = timeout;

    syncFlowRunHistoryPolling(state, {
      visible: () => false,
      hasRunsToPoll: () => true,
      loadRuns: async () => {},
      clearTimeoutFn: (value) => {
        clearedTimeout = value;
      }
    });

    expect(clearedTimeout).toBe(timeout);
    expect(state.pollTimeout).toBeNull();
  });

  it("clears polling on destroy", () => {
    const state = createFlowRunHistoryState();
    const timeout = 1;
    let clearedTimeout: FlowRunHistoryPollTimeout | null = null;
    state.pollTimeout = timeout;

    destroyFlowRunHistoryPolling(state, (value) => {
      clearedTimeout = value;
    });

    expect(clearedTimeout).toBe(timeout);
    expect(state.pollTimeout).toBeNull();
  });
});
