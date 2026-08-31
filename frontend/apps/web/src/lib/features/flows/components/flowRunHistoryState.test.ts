import type { FlowRun } from "@eneo/eneo-js";
import { describe, expect, it } from "vitest";
import {
  createFlowRunHistoryState,
  destroyFlowRunHistoryPolling,
  FLOW_RUN_HISTORY_PAGE_SIZE,
  type FlowRunHistoryPollTimeout,
  loadFlowRunHistory,
  MAX_LOADED_FLOW_RUNS,
  syncFlowRunHistoryFlow,
  syncFlowRunHistoryPolling,
  syncFlowRunHistoryReload
} from "./flowRunHistoryState";
import { makeFlowRun } from "./flowRunHistoryTestFixtures";

function run(id: string, status: FlowRun["status"] = "completed"): FlowRun {
  return makeFlowRun({ id, status });
}

function page(items: FlowRun[], hasMore: boolean) {
  return { items, has_more: hasMore };
}

describe("loadFlowRunHistory", () => {
  it("loads the newest page and records has_more", async () => {
    const state = createFlowRunHistoryState();
    const calls: Array<{ limit: number; offset: number }> = [];

    const result = await loadFlowRunHistory(state, {
      flowId: "flow-1",
      listRuns: async (_flowId, pageArg) => {
        calls.push(pageArg);
        return page([run("run-1")], true);
      },
      getErrorMessage: () => "failed"
    });

    expect(result.kind).toBe("loaded");
    expect(calls).toEqual([{ limit: FLOW_RUN_HISTORY_PAGE_SIZE, offset: 0 }]);
    expect(state.runs.map((item) => item.id)).toEqual(["run-1"]);
    expect(state.hasMore).toBe(true);
    expect(state.nextOffset).toBe(1);
    expect(state.loading).toBe(false);
    expect(state.loadError).toBeNull();
    expect(state.refreshWarning).toBeNull();
    expect(state.isInitialLoad).toBe(false);
    expect(state.inFlightGeneration).toBeNull();
  });

  it("clears runs when no flow is selected", async () => {
    const state = createFlowRunHistoryState();
    state.runs = [run("old-run")];

    const result = await loadFlowRunHistory(state, {
      flowId: null,
      listRuns: async () => page([run("should-not-load")], false),
      getErrorMessage: () => "failed"
    });

    expect(result).toEqual({ kind: "no_flow" });
    expect(state.runs).toEqual([]);
    expect(state.loading).toBe(false);
  });

  it("treats an initial-load failure without usable rows as fatal", async () => {
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
    expect(state.loadError).toBe("backend failed");
    expect(state.loading).toBe(false);
    expect(state.inFlightGeneration).toBeNull();
  });

  it("keeps loaded history usable when a refresh fails", async () => {
    const state = createFlowRunHistoryState();
    state.runs = [run("a")];

    await loadFlowRunHistory(state, {
      flowId: "flow-1",
      listRuns: async () => {
        throw new Error("transient");
      },
      getErrorMessage: () => "transient"
    });

    expect(state.loadError).toBeNull();
    expect(state.refreshWarning).toBe("transient");
    expect(state.runs.map((item) => item.id)).toEqual(["a"]);

    await loadFlowRunHistory(state, {
      flowId: "flow-1",
      listRuns: async () => page([run("a")], false),
      getErrorMessage: () => "failed"
    });

    expect(state.refreshWarning).toBeNull();
  });

  it("does not start a second load of the same generation while one is running", async () => {
    const state = createFlowRunHistoryState();
    state.inFlightGeneration = state.requestGeneration;

    const result = await loadFlowRunHistory(state, {
      flowId: "flow-1",
      listRuns: async () => page([run("should-not-load")], false),
      getErrorMessage: () => "failed"
    });

    expect(result).toEqual({ kind: "already_loading" });
  });
});

describe("refresh merge", () => {
  it("merges the newest page by id: prepends new runs, updates known ones, keeps older objects", async () => {
    const state = createFlowRunHistoryState();
    const oldA = run("a", "running");
    const oldB = run("b");
    state.runs = [oldA, oldB];
    state.nextOffset = 2;
    state.hasMore = true;

    const updatedA = run("a", "completed");
    await loadFlowRunHistory(state, {
      flowId: "flow-1",
      listRuns: async () => page([run("new"), updatedA], true),
      getErrorMessage: () => "failed"
    });

    expect(state.runs.map((item) => item.id)).toEqual(["new", "a", "b"]);
    expect(state.runs[1]).toBe(updatedA);
    // Older rows outside the newest page keep their identity, which keeps
    // their cached search haystacks valid.
    expect(state.runs[2]).toBe(oldB);
    // The prepended new row shifted every backend offset by one.
    expect(state.nextOffset).toBe(3);
  });

  it("does not downgrade hasMore when the loaded window is larger than the page", async () => {
    const state = createFlowRunHistoryState();
    state.runs = Array.from({ length: 60 }, (_, i) => run(`r${i}`));
    state.nextOffset = 60;
    state.hasMore = true;

    await loadFlowRunHistory(state, {
      flowId: "flow-1",
      listRuns: async () => page([run("r0")], false),
      getErrorMessage: () => "failed"
    });

    expect(state.hasMore).toBe(true);
  });

  it("refreshes loaded pollable runs outside the newest page via getRun", async () => {
    const state = createFlowRunHistoryState();
    state.runs = [run("recent"), run("old-active", "running")];
    const fetched: string[] = [];

    await loadFlowRunHistory(state, {
      flowId: "flow-1",
      listRuns: async () => page([run("recent")], false),
      pollableRefresh: {
        getStatus: async (_flowId, runId) => {
          fetched.push(runId);
          return run(runId, "completed");
        },
        shouldPollRun: (item) => item.status === "running"
      },
      getErrorMessage: () => "failed"
    });

    expect(fetched).toEqual(["old-active"]);
    expect(state.runs.find((item) => item.id === "old-active")?.status).toBe("completed");
  });

  it("rotates the bounded straggler budget so no pollable row starves", async () => {
    const state = createFlowRunHistoryState();
    state.runs = [
      run("recent"),
      ...Array.from({ length: 11 }, (_, i) => run(`active-${i + 1}`, "running"))
    ];
    const fetched: string[] = [];
    const options = {
      flowId: "flow-1",
      listRuns: async () => page([run("recent")], false),
      pollableRefresh: {
        getStatus: async (_flowId: string, runId: string) => {
          fetched.push(runId);
          // Stay running so the pollable set does not shrink between cycles.
          return run(runId, "running");
        },
        shouldPollRun: (item: FlowRun) => item.status === "running"
      },
      getErrorMessage: () => "failed"
    };

    await loadFlowRunHistory(state, options);
    await loadFlowRunHistory(state, options);

    expect(fetched).toHaveLength(20);
    expect(fetched).toContain("active-11");
  });

  it("leaves a straggler stale and the history usable when its fetch fails", async () => {
    const state = createFlowRunHistoryState();
    state.runs = [run("recent"), run("gone", "running"), run("alive", "running")];
    const fetched: string[] = [];

    const result = await loadFlowRunHistory(state, {
      flowId: "flow-1",
      listRuns: async () => page([run("recent")], false),
      pollableRefresh: {
        getStatus: async (_flowId, runId) => {
          fetched.push(runId);
          if (runId === "gone") throw new Error("404");
          return run(runId, "completed");
        },
        shouldPollRun: (item) => item.status === "running"
      },
      getErrorMessage: () => "failed"
    });

    expect(result.kind).toBe("loaded");
    expect(state.loadError).toBeNull();
    expect(state.refreshWarning).toBe("failed");
    expect(fetched).toEqual(["gone", "alive"]);
    expect(state.runs.find((item) => item.id === "gone")?.status).toBe("running");
    expect(state.runs.find((item) => item.id === "alive")?.status).toBe("completed");
  });
});

describe("refresh window anchoring", () => {
  it("resets to the newest page when a burst of inserts breaks contiguity", async () => {
    const state = createFlowRunHistoryState();
    state.runs = Array.from({ length: 50 }, (_, i) => run(`old-${i}`));
    state.nextOffset = 50;
    state.hasMore = false;

    // Sixty newer runs arrived: the newest page shares no id with the
    // loaded window, so the gap size is unknowable from the client.
    const newest = Array.from({ length: 50 }, (_, i) => run(`new-${i}`));
    await loadFlowRunHistory(state, {
      flowId: "flow-1",
      listRuns: async () => page(newest, true),
      getErrorMessage: () => "failed"
    });

    // The provable contiguous window is exactly the newest page; load-more
    // continues from offset 50 and re-reaches the older rows without holes.
    expect(state.runs.map((item) => item.id)).toEqual(newest.map((item) => item.id));
    expect(state.nextOffset).toBe(50);
    expect(state.hasMore).toBe(true);
  });
});

describe("load more", () => {
  it("requests only the remaining capacity near the budget and never exceeds it", async () => {
    const state = createFlowRunHistoryState();
    state.runs = Array.from({ length: MAX_LOADED_FLOW_RUNS - 25 }, (_, i) => run(`r${i}`));
    state.nextOffset = state.runs.length;
    state.hasMore = true;
    const calls: Array<{ limit: number; offset: number }> = [];

    await loadFlowRunHistory(state, {
      flowId: "flow-1",
      mode: "more",
      listRuns: async (_flowId, pageArg) => {
        calls.push(pageArg);
        return page(
          Array.from({ length: pageArg.limit }, (_, i) => run(`tail-${i}`)),
          true
        );
      },
      getErrorMessage: () => "failed"
    });

    expect(calls).toEqual([{ limit: 25, offset: MAX_LOADED_FLOW_RUNS - 25 }]);
    expect(state.runs).toHaveLength(MAX_LOADED_FLOW_RUNS);
    expect(state.nextOffset).toBe(MAX_LOADED_FLOW_RUNS);
  });

  it("keeps the budget an invariant when a refresh prepends into a full window", async () => {
    const state = createFlowRunHistoryState();
    state.runs = Array.from({ length: MAX_LOADED_FLOW_RUNS }, (_, i) => run(`r${i}`));
    state.nextOffset = MAX_LOADED_FLOW_RUNS;
    state.hasMore = true;

    // The newest page overlaps the window (r0 present) and carries fresh rows.
    await loadFlowRunHistory(state, {
      flowId: "flow-1",
      listRuns: async () => page([run("fresh-1"), run("fresh-2"), run("r0")], true),
      getErrorMessage: () => "failed"
    });

    expect(state.runs).toHaveLength(MAX_LOADED_FLOW_RUNS);
    expect(state.runs[0].id).toBe("fresh-1");
    // The oldest tail rows were evicted; the retained rows are exactly the
    // newest backend prefix.
    expect(state.nextOffset).toBe(MAX_LOADED_FLOW_RUNS);
    expect(state.hasMore).toBe(true);
  });

  it("stands down at the retained-window budget without a request", async () => {
    const state = createFlowRunHistoryState();
    state.runs = Array.from({ length: MAX_LOADED_FLOW_RUNS }, (_, i) => run(`r${i}`));
    state.hasMore = true;
    let requests = 0;

    const result = await loadFlowRunHistory(state, {
      flowId: "flow-1",
      mode: "more",
      listRuns: async () => {
        requests += 1;
        return page([], false);
      },
      getErrorMessage: () => "failed"
    });

    expect(result).toEqual({ kind: "window_full" });
    expect(requests).toBe(0);
    expect(state.hasMore).toBe(true);
  });

  it("requests the state-owned offset and appends deduplicated", async () => {
    const state = createFlowRunHistoryState();
    state.runs = [run("a"), run("b")];
    state.nextOffset = 2;
    const calls: Array<{ limit: number; offset: number }> = [];

    await loadFlowRunHistory(state, {
      flowId: "flow-1",
      mode: "more",
      listRuns: async (_flowId, pageArg) => {
        calls.push(pageArg);
        // "b" comes back because a new run shifted offsets meanwhile.
        return page([run("b"), run("c")], false);
      },
      getErrorMessage: () => "failed"
    });

    expect(calls).toEqual([{ limit: FLOW_RUN_HISTORY_PAGE_SIZE, offset: 2 }]);
    expect(state.runs.map((item) => item.id)).toEqual(["a", "b", "c"]);
    expect(state.hasMore).toBe(false);
    expect(state.nextOffset).toBe(4);
  });

  it("makes forward progress even when a page deduplicates to nothing", async () => {
    const state = createFlowRunHistoryState();
    state.runs = [run("a"), run("b")];
    state.nextOffset = 2;
    const offsets: number[] = [];
    const options = {
      flowId: "flow-1",
      mode: "more" as const,
      listRuns: async (_flowId: string, pageArg: { limit: number; offset: number }) => {
        offsets.push(pageArg.offset);
        // The whole page is already loaded (rows shifted); nothing fresh.
        return offsets.length === 1 ? page([run("a"), run("b")], true) : page([run("c")], false);
      },
      getErrorMessage: () => "failed"
    };

    await loadFlowRunHistory(state, options);
    await loadFlowRunHistory(state, options);

    // Offsets advance by rows consumed, not by display growth.
    expect(offsets).toEqual([2, 4]);
    expect(state.runs.map((item) => item.id)).toEqual(["a", "b", "c"]);
  });

  it("records a nonfatal load-more error and retries the same offset", async () => {
    const state = createFlowRunHistoryState();
    state.runs = [run("a")];
    state.nextOffset = 1;
    state.hasMore = true;
    const offsets: number[] = [];
    let failFirst = true;

    const options = {
      flowId: "flow-1",
      mode: "more" as const,
      listRuns: async (_flowId: string, pageArg: { limit: number; offset: number }) => {
        offsets.push(pageArg.offset);
        if (failFirst) {
          failFirst = false;
          throw new Error("boom");
        }
        return page([run("b")], false);
      },
      getErrorMessage: () => "boom"
    };

    await loadFlowRunHistory(state, options);
    expect(state.loadMoreError).toBe("boom");
    expect(state.loadError).toBeNull();
    expect(state.runs.map((item) => item.id)).toEqual(["a"]);

    await loadFlowRunHistory(state, options);
    expect(offsets).toEqual([1, 1]);
    expect(state.loadMoreError).toBeNull();
    expect(state.runs.map((item) => item.id)).toEqual(["a", "b"]);
  });
});

describe("stale responses", () => {
  it("discards a response that resolves after a flow switch", async () => {
    const state = createFlowRunHistoryState();
    let release: () => void = () => {};

    const pending = loadFlowRunHistory(state, {
      flowId: "flow-1",
      listRuns: () =>
        new Promise((resolve) => {
          release = () => resolve(page([run("stale")], false));
        }),
      getErrorMessage: () => "failed"
    });

    syncFlowRunHistoryFlow(state, "flow-2");
    state.runs = [run("fresh")];
    release();

    const result = await pending;
    expect(result).toEqual({ kind: "stale" });
    expect(state.runs.map((item) => item.id)).toEqual(["fresh"]);
  });

  it("lets the new flow load while a superseded load is still in flight", async () => {
    const state = createFlowRunHistoryState();
    let release: () => void = () => {};

    const stalePending = loadFlowRunHistory(state, {
      flowId: "flow-1",
      listRuns: () =>
        new Promise((resolve) => {
          release = () => resolve(page([run("stale")], false));
        }),
      getErrorMessage: () => "failed"
    });

    syncFlowRunHistoryFlow(state, "flow-2");

    const result = await loadFlowRunHistory(state, {
      flowId: "flow-2",
      listRuns: async () => page([run("fresh")], false),
      getErrorMessage: () => "failed"
    });

    expect(result.kind).toBe("loaded");
    expect(state.runs.map((item) => item.id)).toEqual(["fresh"]);

    release();
    await stalePending;
    expect(state.runs.map((item) => item.id)).toEqual(["fresh"]);
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

  it("atomically resets the loaded window on flow change", () => {
    const state = createFlowRunHistoryState();
    syncFlowRunHistoryFlow(state, "flow-1");
    state.runs = [run("run-1")];
    state.hasMore = true;
    state.nextOffset = 50;
    state.loadError = "old error";
    state.refreshWarning = "old warning";
    state.loadMoreError = "old more error";
    const generation = state.requestGeneration;

    expect(syncFlowRunHistoryFlow(state, "flow-2")).toBe(true);
    expect(state.runs).toEqual([]);
    expect(state.hasMore).toBe(false);
    expect(state.nextOffset).toBe(0);
    expect(state.loadError).toBeNull();
    expect(state.refreshWarning).toBeNull();
    expect(state.loadMoreError).toBeNull();
    expect(state.requestGeneration).toBe(generation + 1);
  });

  it("clears stale runs when there is no flow id, idempotently", () => {
    const state = createFlowRunHistoryState();
    state.lastLoadedFlowId = "flow-1";
    state.runs = [run("run-1")];
    state.loading = true;

    expect(syncFlowRunHistoryFlow(state, null)).toBe(false);
    expect(state.lastLoadedFlowId).toBeNull();
    expect(state.runs).toEqual([]);
    expect(state.loading).toBe(false);
    const generation = state.requestGeneration;

    // A repeated null sync is a no-op: the generation must not churn.
    expect(syncFlowRunHistoryFlow(state, null)).toBe(false);
    expect(state.requestGeneration).toBe(generation);
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
