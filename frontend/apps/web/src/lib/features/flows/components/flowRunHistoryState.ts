import type { FlowRunSummary } from "@eneo/eneo-js";

export interface FlowRunHistoryState {
  runs: FlowRunSummary[];
  loading: boolean;
  loadError: string | null;
  /** Non-fatal failure from refreshing history that is already usable. */
  refreshWarning: string | null;
  lastLoadedFlowId: string | null;
  isInitialLoad: boolean;
  lastHandledReloadTrigger: number;
  /**
   * Generation of the load currently in flight, or null. A load from a
   * previous generation (superseded by a flow switch) does not block a
   * new one and cannot clear the new one's marker.
   */
  inFlightGeneration: number | null;
  pollTimeout: FlowRunHistoryPollTimeout | null;
  /** True when the server reports more rows past the loaded window. */
  hasMore: boolean;
  /**
   * The backend pagination position: how many backend rows the window has
   * consumed. Owned here — deduplication and optimistic display rows never
   * move it, so load-more always makes forward progress.
   */
  nextOffset: number;
  /** Failure of the last load-more request; retrying reuses nextOffset. */
  loadMoreError: string | null;
  /** Round-robin position for the bounded stale-pollable-run refresh. */
  pollRotation: number;
  /**
   * Incremented on every flow switch. A response captured under an older
   * generation is discarded so a stale in-flight request can never
   * overwrite the new flow's window.
   */
  requestGeneration: number;
}

export type FlowRunHistoryPollTimeout = number | ReturnType<typeof setTimeout>;

export interface FlowRunHistoryListResult {
  items: FlowRunSummary[];
  has_more: boolean;
}

export type FlowRunHistoryLoadResult =
  | { kind: "loaded"; runs: FlowRunSummary[] }
  | { kind: "failed"; message: string; error: unknown }
  | { kind: "no_flow" }
  | { kind: "already_loading" }
  | { kind: "stale" }
  | { kind: "window_full" };

export type FlowRunHistoryLoadMode = "refresh" | "more";

export interface LoadFlowRunHistoryOptions {
  flowId: string | null | undefined;
  mode?: FlowRunHistoryLoadMode;
  listRuns: (
    flowId: string,
    page: { limit: number; offset: number }
  ) => Promise<FlowRunHistoryListResult>;
  /**
   * Refreshes loaded pollable runs that have scrolled past the newest page.
   * The two callbacks are coupled so a half-configuration is impossible;
   * omitting the pair leaves those rows stale until the user reloads.
   */
  pollableRefresh?: {
    getStatus: (flowId: string, runId: string) => Promise<FlowRunSummary>;
    shouldPollRun: (run: FlowRunSummary) => boolean;
  };
  getErrorMessage: (error: unknown) => string;
}

export interface SyncFlowRunHistoryPollingOptions {
  visible: () => boolean;
  hasRunsToPoll: () => boolean;
  loadRuns: () => Promise<unknown>;
  setTimeoutFn?: (
    callback: () => void | Promise<void>,
    delayMs: number
  ) => FlowRunHistoryPollTimeout;
  clearTimeoutFn?: (timeout: FlowRunHistoryPollTimeout) => void;
  pollIntervalMs?: number;
}

export const FLOW_RUN_HISTORY_PAGE_SIZE = 50;

/**
 * Retained-window budget: the loaded window, cached search text, and rendered
 * rows all scale with this bound. The list contract is a content-free summary;
 * sensitive input and results are fetched only through audited detail routes.
 */
export const MAX_LOADED_FLOW_RUNS = 200;

/** Upper bound on per-refresh single-run fetches for stale pollable runs. */
const MAX_POLLABLE_RUN_REFRESHES = 10;

export function createFlowRunHistoryState(): FlowRunHistoryState {
  return {
    runs: [],
    loading: true,
    loadError: null,
    refreshWarning: null,
    lastLoadedFlowId: null,
    isInitialLoad: true,
    lastHandledReloadTrigger: 0,
    inFlightGeneration: null,
    pollTimeout: null,
    hasMore: false,
    nextOffset: 0,
    loadMoreError: null,
    pollRotation: 0,
    requestGeneration: 0
  };
}

/**
 * Loads run history with a bounded request budget per call:
 *
 * - "refresh" (initial load, reload trigger, polling): fetches ONE newest
 *   page and merges it by run id into the loaded window — rows in the
 *   response are replaced, new runs are prepended, and older loaded rows
 *   keep their object identity (which also keeps their cached search
 *   haystacks valid). Loaded non-terminal runs outside the newest page are
 *   refreshed individually, capped at MAX_POLLABLE_RUN_REFRESHES.
 * - "more": fetches ONE page after the loaded window and appends it,
 *   deduplicated by run id (a run inserted meanwhile shifts offsets, so
 *   the same row can come back; the window is eventually consistent, not
 *   an exact snapshot).
 */
export async function loadFlowRunHistory(
  state: FlowRunHistoryState,
  options: LoadFlowRunHistoryOptions
): Promise<FlowRunHistoryLoadResult> {
  const generation = state.requestGeneration;
  if (state.inFlightGeneration === generation) return { kind: "already_loading" };

  state.inFlightGeneration = generation;
  if (!options.flowId) {
    state.runs = [];
    state.loading = false;
    state.refreshWarning = null;
    state.inFlightGeneration = null;
    return { kind: "no_flow" };
  }

  if (state.isInitialLoad) state.loading = true;
  state.loadError = null;
  const mode: FlowRunHistoryLoadMode = options.mode ?? "refresh";

  try {
    if (mode === "more") {
      const remainingCapacity = MAX_LOADED_FLOW_RUNS - state.runs.length;
      if (remainingCapacity <= 0) {
        return { kind: "window_full" };
      }
      const result = await options.listRuns(options.flowId, {
        limit: Math.min(FLOW_RUN_HISTORY_PAGE_SIZE, remainingCapacity),
        offset: state.nextOffset
      });
      if (generation !== state.requestGeneration) return { kind: "stale" };
      const loadedIds = new Set(state.runs.map((run) => run.id));
      const fresh = result.items.filter((run) => !loadedIds.has(run.id));
      state.runs = [...state.runs, ...fresh].slice(0, MAX_LOADED_FLOW_RUNS);
      // Every returned row was consumed from the backend position, even
      // when deduplication drops it from the display set.
      state.nextOffset += result.items.length;
      state.hasMore = result.has_more;
      state.loadMoreError = null;
    } else {
      const result = await options.listRuns(options.flowId, {
        limit: FLOW_RUN_HISTORY_PAGE_SIZE,
        offset: 0
      });
      if (generation !== state.requestGeneration) return { kind: "stale" };
      const loadedIds = new Set(state.runs.map((run) => run.id));
      const overlaps = state.runs.length === 0 || result.items.some((run) => loadedIds.has(run.id));
      if (!overlaps) {
        // A burst of inserts pushed every loaded row out of the newest
        // page: the gap between the page and the old window is unknown,
        // so the only contiguous window we can prove is the page itself.
        state.runs = result.items;
        state.nextOffset = result.items.length;
        state.hasMore = result.has_more;
      } else {
        const before = state.runs.length;
        state.runs = mergeNewestPage(state.runs, result.items);
        // New rows shift every backend offset by their count; consuming
        // them keeps nextOffset pointing right after the last loaded
        // backend row.
        state.nextOffset =
          before === 0 ? result.items.length : state.nextOffset + (state.runs.length - before);
        if (state.runs.length > MAX_LOADED_FLOW_RUNS) {
          // The retained-window budget is an invariant: drop the oldest
          // tail. The retained rows are then exactly the newest backend
          // prefix, so the consumed position equals the budget.
          state.runs = state.runs.slice(0, MAX_LOADED_FLOW_RUNS);
          state.nextOffset = MAX_LOADED_FLOW_RUNS;
        }
        // The response bounds the total only while the backend traversal
        // is still within the first page. Anchored on nextOffset, never on
        // the display length — optimistic rows must not suppress hasMore.
        if (state.nextOffset <= result.items.length) {
          state.hasMore = result.has_more;
        }
      }
      const refreshWarning = await refreshStalePollableRuns(
        state,
        options,
        generation,
        new Set(result.items.map((run) => run.id))
      );
      if (generation !== state.requestGeneration) return { kind: "stale" };
      state.refreshWarning = refreshWarning;
    }
    state.isInitialLoad = false;
    return { kind: "loaded", runs: state.runs };
  } catch (error) {
    if (generation !== state.requestGeneration) return { kind: "stale" };
    const message = options.getErrorMessage(error);
    if (mode === "more") {
      // nextOffset is untouched, so a retry requests the same page.
      state.loadMoreError = message;
    } else if (state.runs.length === 0) {
      // Fatal only when there is no usable history to show.
      state.loadError = message;
      state.refreshWarning = null;
    } else {
      state.refreshWarning = message;
    }
    return { kind: "failed", message, error };
  } finally {
    if (state.inFlightGeneration === generation) {
      state.inFlightGeneration = null;
    }
    if (generation === state.requestGeneration) {
      state.loading = false;
    }
  }
}

function mergeNewestPage(loaded: FlowRunSummary[], page: FlowRunSummary[]): FlowRunSummary[] {
  const pageById = new Map(page.map((run) => [run.id, run]));
  const loadedIds = new Set(loaded.map((run) => run.id));
  const fresh = page.filter((run) => !loadedIds.has(run.id));
  return [...fresh, ...loaded.map((run) => pageById.get(run.id) ?? run)];
}

async function refreshStalePollableRuns(
  state: FlowRunHistoryState,
  options: LoadFlowRunHistoryOptions,
  generation: number,
  covered: Set<string>
): Promise<string | null> {
  const { pollableRefresh, flowId } = options;
  if (!pollableRefresh || !flowId) return null;
  const pollable = state.runs.filter(
    (run) => pollableRefresh.shouldPollRun(run) && !covered.has(run.id)
  );
  if (pollable.length === 0) return null;
  // Round-robin through the pollable stragglers so a large set is refreshed
  // fairly across cycles instead of starving everything past the budget.
  const start = state.pollRotation % pollable.length;
  const rotated = [...pollable.slice(start), ...pollable.slice(0, start)];
  const batch = rotated.slice(0, MAX_POLLABLE_RUN_REFRESHES);
  state.pollRotation = (start + batch.length) % Math.max(pollable.length, 1);
  let warning: string | null = null;
  for (const run of batch) {
    let updated: FlowRunSummary;
    try {
      updated = await pollableRefresh.getStatus(flowId, run.id);
    } catch (error) {
      warning ??= options.getErrorMessage(error);
      continue;
    }
    if (generation !== state.requestGeneration) return warning;
    state.runs = state.runs.map((existing) => (existing.id === updated.id ? updated : existing));
  }
  return warning;
}

/**
 * Returns true when the given flow needs a fresh load. A flow change is an
 * atomic window reset: runs, pagination, and error state all clear, and the
 * request generation advances so stale in-flight responses are discarded.
 */
export function syncFlowRunHistoryFlow(
  state: FlowRunHistoryState,
  flowId: string | null | undefined
): boolean {
  if (flowId && flowId !== state.lastLoadedFlowId) {
    state.lastLoadedFlowId = flowId;
    state.isInitialLoad = true;
    state.runs = [];
    state.hasMore = false;
    state.nextOffset = 0;
    state.loadError = null;
    state.refreshWarning = null;
    state.loadMoreError = null;
    state.pollRotation = 0;
    state.requestGeneration += 1;
    return true;
  }

  if (!flowId && state.lastLoadedFlowId !== null) {
    state.lastLoadedFlowId = null;
    state.runs = [];
    state.hasMore = false;
    state.nextOffset = 0;
    state.loadError = null;
    state.refreshWarning = null;
    state.loadMoreError = null;
    state.pollRotation = 0;
    state.loading = false;
    state.requestGeneration += 1;
  }

  return false;
}

export function syncFlowRunHistoryReload(
  state: FlowRunHistoryState,
  reloadTrigger: number
): boolean {
  if (reloadTrigger <= state.lastHandledReloadTrigger) return false;

  state.lastHandledReloadTrigger = reloadTrigger;
  return true;
}

export function syncFlowRunHistoryPolling(
  state: FlowRunHistoryState,
  options: SyncFlowRunHistoryPollingOptions
) {
  const {
    visible,
    hasRunsToPoll,
    loadRuns,
    setTimeoutFn = setTimeout,
    clearTimeoutFn = clearTimeout,
    pollIntervalMs = 5000
  } = options;

  if (hasRunsToPoll() && !state.pollTimeout && visible()) {
    const scheduleNextPoll = () => {
      state.pollTimeout = setTimeoutFn(async () => {
        try {
          await loadRuns();
        } finally {
          state.pollTimeout = null;
        }
        if (hasRunsToPoll() && visible()) {
          scheduleNextPoll();
        }
      }, pollIntervalMs);
    };
    scheduleNextPoll();
    return;
  }

  if ((!hasRunsToPoll() || !visible()) && state.pollTimeout) {
    clearTimeoutFn(state.pollTimeout);
    state.pollTimeout = null;
  }
}

export function destroyFlowRunHistoryPolling(
  state: FlowRunHistoryState,
  clearTimeoutFn: (timeout: FlowRunHistoryPollTimeout) => void = clearTimeout
) {
  if (!state.pollTimeout) return;
  clearTimeoutFn(state.pollTimeout);
  state.pollTimeout = null;
}
