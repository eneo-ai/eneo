import type { FlowRunSummary } from "@eneo/eneo-js";
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

export function createFlowRunStatusCounts(runs: FlowRunSummary[]): Record<FlowRunStatus, number> {
  const counts = Object.fromEntries(FLOW_RUN_STATUS_VALUES.map((status) => [status, 0])) as Record<
    FlowRunStatus,
    number
  >;

  for (const run of runs) {
    counts[run.status] = (counts[run.status] ?? 0) + 1;
  }

  return counts;
}

export function getFlowRunDurationMs(run: FlowRunSummary): number | null {
  const startRaw = run.started_at ?? run.created_at;
  const finishRaw = run.finished_at;
  if (!startRaw || !finishRaw) return null;

  const start = new Date(startRaw).getTime();
  const finish = new Date(finishRaw).getTime();
  if (Number.isNaN(start) || Number.isNaN(finish)) return null;

  return finish - start;
}

const searchHaystackCache = new WeakMap<FlowRunSummary, { labelsKey: string; haystack: string }>();

export interface FlowRunSearchLabels {
  /** Cache key for the label set — pass the active locale. */
  labelsKey: string;
  getStatusLabel: (status: string) => string;
  /** The date string the table renders, so search matches what users see. */
  getDateLabel: (run: FlowRunSummary) => string;
}

function getFlowRunSearchHaystack(run: FlowRunSummary, labels: FlowRunSearchLabels): string {
  const cached = searchHaystackCache.get(run);
  if (cached && cached.labelsKey === labels.labelsKey) return cached.haystack;
  const haystack = [
    run.id,
    run.created_at ?? "",
    labels.getDateLabel(run),
    labels.getStatusLabel(run.status),
    `v${run.flow_version}`
  ]
    .join("\n")
    .toLowerCase();
  searchHaystackCache.set(run, { labelsKey: labels.labelsKey, haystack });
  return haystack;
}

export function matchesFlowRunSearch(
  run: FlowRunSummary,
  normalizedQuery: string,
  labels: FlowRunSearchLabels
): boolean {
  if (!normalizedQuery) return true;
  return getFlowRunSearchHaystack(run, labels).includes(normalizedQuery);
}

/**
 * Sorting depends only on the run set and sort state, so it lives in its
 * own derived step: a search keystroke re-filters the already-sorted list
 * in O(N) instead of re-sorting on every input.
 */
export function sortFlowRuns(
  runs: FlowRunSummary[],
  sortState: FlowRunHistorySortState
): FlowRunSummary[] {
  return [...runs].sort((a, b) => {
    const primary = compareFlowRuns(a, b, sortState.key);
    const comparison = primary === 0 ? a.id.localeCompare(b.id) : primary;
    return sortState.dir === "asc" ? comparison : -comparison;
  });
}

/** Order-preserving filter over an already-sorted list. */
export function filterFlowRuns(
  sortedRuns: FlowRunSummary[],
  options: {
    statusFilter: FlowRunStatusFilter;
    searchQuery?: string;
    labels: FlowRunSearchLabels;
  }
): FlowRunSummary[] {
  const normalizedQuery = (options.searchQuery ?? "").trim().toLowerCase();
  const searched = normalizedQuery
    ? sortedRuns.filter((run) => matchesFlowRunSearch(run, normalizedQuery, options.labels))
    : sortedRuns;
  return options.statusFilter
    ? searched.filter((run) => run.status === options.statusFilter)
    : searched;
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

function compareFlowRuns(a: FlowRunSummary, b: FlowRunSummary, key: FlowRunHistorySortKey): number {
  if (key === "started") {
    return getStartedAtMs(a) - getStartedAtMs(b);
  }
  if (key === "duration") {
    return compareNullableNumbers(getFlowRunDurationMs(a), getFlowRunDurationMs(b));
  }
  return a.status.localeCompare(b.status);
}

function getStartedAtMs(run: FlowRunSummary): number {
  const startedAt = new Date(run.started_at ?? run.created_at ?? 0).getTime();
  return Number.isNaN(startedAt) ? 0 : startedAt;
}

function compareNullableNumbers(a: number | null, b: number | null): number {
  if (a === null && b === null) return 0;
  if (a === null) return -1;
  if (b === null) return 1;
  return a - b;
}
