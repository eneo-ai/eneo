import type { FlowRun } from "@eneo/eneo-js";
import {
  FLOW_RUN_STATUS_VALUES,
  type FlowRunStatus,
  type FlowRunStatusFilter
} from "./flowRunStatusSets";

export type FlowRunHistorySortKey = "started" | "duration" | "status";
export type FlowRunHistorySortDir = "asc" | "desc";

export type FlowRunHistorySortState = {
  key: FlowRunHistorySortKey;
  dir: FlowRunHistorySortDir;
};

export const DEFAULT_FLOW_RUN_HISTORY_SORT: FlowRunHistorySortState = {
  key: "started",
  dir: "desc"
};

export function createFlowRunStatusCounts(runs: FlowRun[]): Record<FlowRunStatus, number> {
  const counts = Object.fromEntries(FLOW_RUN_STATUS_VALUES.map((status) => [status, 0])) as Record<
    FlowRunStatus,
    number
  >;

  for (const run of runs) {
    counts[run.status] = (counts[run.status] ?? 0) + 1;
  }

  return counts;
}

export function getFlowRunDurationMs(run: FlowRun): number | null {
  const startRaw = run.started_at ?? run.created_at;
  const finishRaw = run.finished_at;
  if (!startRaw || !finishRaw) return null;

  const start = new Date(startRaw).getTime();
  const finish = new Date(finishRaw).getTime();
  if (Number.isNaN(start) || Number.isNaN(finish)) return null;

  return finish - start;
}

export function getVisibleFlowRuns(
  runs: FlowRun[],
  options: {
    statusFilter: FlowRunStatusFilter;
    sortState: FlowRunHistorySortState;
  }
): FlowRun[] {
  const filtered = options.statusFilter
    ? runs.filter((run) => run.status === options.statusFilter)
    : runs;

  return [...filtered].sort((a, b) => {
    const primary = compareFlowRuns(a, b, options.sortState.key);
    const comparison = primary === 0 ? a.id.localeCompare(b.id) : primary;
    return options.sortState.dir === "asc" ? comparison : -comparison;
  });
}

export function nextFlowRunHistorySortState(
  current: FlowRunHistorySortState,
  key: FlowRunHistorySortKey
): FlowRunHistorySortState {
  if (current.key === key) {
    return {
      key,
      dir: current.dir === "asc" ? "desc" : "asc"
    };
  }

  return {
    key,
    dir: key === "status" ? "asc" : "desc"
  };
}

export function getFlowRunHistoryAriaSort(
  sortState: FlowRunHistorySortState,
  key: FlowRunHistorySortKey
): "ascending" | "descending" | "none" {
  if (sortState.key !== key) return "none";
  return sortState.dir === "asc" ? "ascending" : "descending";
}

function compareFlowRuns(a: FlowRun, b: FlowRun, key: FlowRunHistorySortKey): number {
  if (key === "started") {
    return getStartedAtMs(a) - getStartedAtMs(b);
  }
  if (key === "duration") {
    return compareNullableNumbers(getFlowRunDurationMs(a), getFlowRunDurationMs(b));
  }
  return a.status.localeCompare(b.status);
}

function getStartedAtMs(run: FlowRun): number {
  const startedAt = new Date(run.started_at ?? run.created_at ?? 0).getTime();
  return Number.isNaN(startedAt) ? 0 : startedAt;
}

function compareNullableNumbers(a: number | null, b: number | null): number {
  if (a === null && b === null) return 0;
  if (a === null) return -1;
  if (b === null) return 1;
  return a - b;
}
