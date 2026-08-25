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

// Rebuilding every run's search text — and formatting its localized
// date — is the hot cost at the 200-row window budget, so both are cached.
// The haystack is built once per run row and cached by object identity
// (a window refetch creates new rows, which naturally invalidates the
// cache); the label callbacks run only on a cache miss, keyed by the
// caller-provided labelsKey (locale), so a locale change rebuilds.
const searchHaystackCache = new WeakMap<FlowRun, { labelsKey: string; haystack: string }>();

export interface FlowRunSearchLabels {
  /** Cache key for the label set — pass the active locale. */
  labelsKey: string;
  getStatusLabel: (status: string) => string;
  /** The date string the table renders, so search matches what users see. */
  getDateLabel: (run: FlowRun) => string;
}

/**
 * Bounded search text from a run's input: top-level primitive values and
 * arrays of primitives (multiselect answers), values sliced BEFORE any
 * concatenation, with an exact character budget — neither build cost nor
 * cache size scales with the 1 MiB-per-run payload contract. Deep-nested
 * object search needs a server contract and is a named follow-up.
 */
const INPUT_SEARCH_TEXT_MAX_CHARS = 2000;
const INPUT_SEARCH_VALUE_MAX_CHARS = 200;

const inputSearchTextCache = new WeakMap<object, string>();

/**
 * Builds (and caches) the bounded input search text for a run. The table
 * primes this when rows are CONSUMED from the backend, so even a hostile
 * payload's enumeration cost lands on the load path — never on a search
 * keystroke.
 */
export function primeFlowRunInputSearchText(run: FlowRun): void {
  const payload = run.input_payload_json;
  if (typeof payload !== "object" || payload === null) return;
  if (!inputSearchTextCache.has(payload)) {
    inputSearchTextCache.set(payload, buildShallowInputSearchText(payload));
  }
}

function collectShallowInputSearchText(payload: FlowRun["input_payload_json"]): string {
  if (typeof payload === "object" && payload !== null) {
    const cached = inputSearchTextCache.get(payload);
    if (cached !== undefined) return cached;
    const built = buildShallowInputSearchText(payload);
    inputSearchTextCache.set(payload, built);
    return built;
  }
  return buildShallowInputSearchText(payload);
}

function buildShallowInputSearchText(payload: FlowRun["input_payload_json"]): string {
  if (typeof payload !== "object" || payload === null) {
    return String(payload ?? "").slice(0, INPUT_SEARCH_TEXT_MAX_CHARS);
  }
  const parts: string[] = [];
  let remaining = INPUT_SEARCH_TEXT_MAX_CHARS;
  const push = (text: string) => {
    if (remaining <= 0) return false;
    const clipped = text.slice(0, remaining);
    parts.push(clipped);
    remaining -= clipped.length + 1; // account for the join separator
    return remaining > 0;
  };
  let keysVisited = 0;
  for (const key in payload) {
    // for-in enumerates lazily; a hostile 35k-key payload stops here
    // without materializing the whole keyset the way Object.keys does.
    if (++keysVisited > 300) break;
    if (remaining <= 0) break;
    if (!push(key)) break;
    const value = (payload as Record<string, unknown>)[key];
    if (typeof value === "string") {
      if (!push(value.slice(0, INPUT_SEARCH_VALUE_MAX_CHARS))) break;
    } else if (typeof value === "number" || typeof value === "boolean") {
      if (!push(String(value))) break;
    } else if (Array.isArray(value)) {
      for (const item of value) {
        if (typeof item === "string") {
          if (!push(item.slice(0, INPUT_SEARCH_VALUE_MAX_CHARS))) break;
        } else if (typeof item === "number" || typeof item === "boolean") {
          if (!push(String(item))) break;
        }
        if (remaining <= 0) break;
      }
    }
  }
  return parts.join("\n");
}

function getFlowRunSearchHaystack(run: FlowRun, labels: FlowRunSearchLabels): string {
  const cached = searchHaystackCache.get(run);
  if (cached && cached.labelsKey === labels.labelsKey) return cached.haystack;
  const haystack = [
    run.id,
    run.created_at ?? "",
    labels.getDateLabel(run),
    labels.getStatusLabel(run.status),
    `v${run.flow_version}`,
    (run.result_files ?? [])
      .slice(0, 20)
      .map((file) => file.name.slice(0, 120))
      .join("\n"),
    collectShallowInputSearchText(run.input_payload_json)
  ]
    .join("\n")
    .toLowerCase();
  searchHaystackCache.set(run, { labelsKey: labels.labelsKey, haystack });
  return haystack;
}

export function matchesFlowRunSearch(
  run: FlowRun,
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
export function sortFlowRuns(runs: FlowRun[], sortState: FlowRunHistorySortState): FlowRun[] {
  return [...runs].sort((a, b) => {
    const primary = compareFlowRuns(a, b, sortState.key);
    const comparison = primary === 0 ? a.id.localeCompare(b.id) : primary;
    return sortState.dir === "asc" ? comparison : -comparison;
  });
}

/** Order-preserving filter over an already-sorted list. */
export function filterFlowRuns(
  sortedRuns: FlowRun[],
  options: {
    statusFilter: FlowRunStatusFilter;
    searchQuery?: string;
    labels: FlowRunSearchLabels;
  }
): FlowRun[] {
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
