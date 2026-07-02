import type { FlowRun } from "@eneo/eneo-js";

export interface FlowRunHistoryState {
  runs: FlowRun[];
  loading: boolean;
  loadError: string | null;
  lastLoadedFlowId: string | null;
  isInitialLoad: boolean;
  lastHandledReloadTrigger: number;
  loadInFlight: boolean;
  pollTimeout: FlowRunHistoryPollTimeout | null;
}

export type FlowRunHistoryPollTimeout = number | ReturnType<typeof setTimeout>;

export type FlowRunHistoryListResult = FlowRun[] | { items?: FlowRun[] };

export type FlowRunHistoryLoadResult =
  | { kind: "loaded"; runs: FlowRun[] }
  | { kind: "failed"; message: string; error: unknown }
  | { kind: "no_flow" }
  | { kind: "already_loading" };

export interface LoadFlowRunHistoryOptions {
  flowId: string | null | undefined;
  listRuns: (flowId: string) => Promise<FlowRunHistoryListResult>;
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

export function createFlowRunHistoryState(): FlowRunHistoryState {
  return {
    runs: [],
    loading: true,
    loadError: null,
    lastLoadedFlowId: null,
    isInitialLoad: true,
    lastHandledReloadTrigger: 0,
    loadInFlight: false,
    pollTimeout: null
  };
}

export async function loadFlowRunHistory(
  state: FlowRunHistoryState,
  options: LoadFlowRunHistoryOptions
): Promise<FlowRunHistoryLoadResult> {
  if (state.loadInFlight) return { kind: "already_loading" };

  state.loadInFlight = true;
  if (!options.flowId) {
    state.runs = [];
    state.loading = false;
    state.loadInFlight = false;
    return { kind: "no_flow" };
  }

  if (state.isInitialLoad) state.loading = true;
  state.loadError = null;

  try {
    const result = await options.listRuns(options.flowId);
    const runs = Array.isArray(result) ? result : (result.items ?? []);
    state.runs = runs;
    state.isInitialLoad = false;
    return { kind: "loaded", runs };
  } catch (error) {
    const message = options.getErrorMessage(error);
    state.loadError = message;
    return { kind: "failed", message, error };
  } finally {
    state.loading = false;
    state.loadInFlight = false;
  }
}

export function syncFlowRunHistoryFlow(
  state: FlowRunHistoryState,
  flowId: string | null | undefined
): boolean {
  if (flowId && flowId !== state.lastLoadedFlowId) {
    state.lastLoadedFlowId = flowId;
    state.isInitialLoad = true;
    return true;
  }

  if (!flowId) {
    state.lastLoadedFlowId = null;
    state.runs = [];
    state.loading = false;
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
