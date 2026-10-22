import { useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import {
  runKeys,
  type RunPublic,
  type RunsFilter,
  type RunStatusCounts,
  type RunSummary
} from "./runs-api";

/**
 * Runs this tab just started, shown in the flow's runs list at once instead
 * of after the list's next read. They are a display overlay: never written
 * into the list's pages, so paging only ever sees the rows the core
 * returned, and shown only while the list's answer is older than the start.
 * The next answer has the run itself.
 */

/** A run this tab started, and when. */
export type StartedRun = { run: RunSummary; startedAt: number };

/** Client state, never fetched: the runs this tab started, newest first. */
export function startedRunsKey(flowId: string) {
  return [...runKeys.all(flowId), "started"] as const;
}

/** The run as the content-free list shows it: its summary, without its input or result. */
export function runSummaryOf(run: RunPublic): RunSummary {
  return {
    id: run.id,
    flow_id: run.flow_id,
    flow_version: run.flow_version,
    tenant_id: run.tenant_id,
    trace_id: run.trace_id,
    status: run.status,
    purpose: run.purpose,
    principal_type: run.principal_type,
    started_by: run.started_by,
    run_label: run.run_label,
    revision: run.revision,
    job_id: run.job_id,
    dispatch_attempt_count: run.dispatch_attempt_count,
    dispatch_pending_since: run.dispatch_pending_since,
    dispatch_next_attempt_at: run.dispatch_next_attempt_at,
    dispatch_last_attempt_at: run.dispatch_last_attempt_at,
    dispatch_last_error: run.dispatch_last_error,
    dispatch_exhausted_at: run.dispatch_exhausted_at,
    dispatched_at: run.dispatched_at,
    created_at: run.created_at,
    started_at: run.started_at,
    finished_at: run.finished_at,
    cancelled_at: run.cancelled_at,
    updated_at: run.updated_at
  };
}

/** Remembers a run the caller just started, for the runs list to show at once. */
export function rememberStartedRun(
  queryClient: QueryClient,
  flowId: string,
  run: RunPublic,
  now: number = Date.now()
): void {
  queryClient.setQueryData<StartedRun[]>(startedRunsKey(flowId), (current = []) => [
    { run: runSummaryOf(run), startedAt: now },
    ...current.filter((item) => item.run.id !== run.id)
  ]);
}

/**
 * Whether a list with this filter would show the started run first: newest
 * first by start, no search (the core matches names the client cannot see),
 * and a status filter the run's status passes. The caller started the run,
 * so "only mine" passes too.
 */
function showsFirst(filter: RunsFilter, run: RunSummary): boolean {
  if (filter.search) return false;
  if (filter.status && filter.status !== run.status) return false;
  return !filter.sort || (filter.sort.key === "started_at" && filter.sort.order === "desc");
}

/**
 * The list's runs with the started runs it does not report yet first, and
 * its status counts with them. `listedAt` is when the list's answer was read:
 * a run started before it is in that answer or, by the filter, is not shown.
 */
export function withStartedRuns(
  listed: readonly RunSummary[],
  counts: RunStatusCounts | undefined,
  started: readonly StartedRun[],
  filter: RunsFilter,
  listedAt: number
): { items: RunSummary[]; counts: RunStatusCounts | undefined } {
  const ids = new Set(listed.map((run) => run.id));
  const extra = started
    .filter(
      (item) => item.startedAt > listedAt && !ids.has(item.run.id) && showsFirst(filter, item.run)
    )
    .map((item) => item.run);
  if (extra.length === 0) return { items: [...listed], counts };
  const nextCounts = counts ? { ...counts } : undefined;
  if (nextCounts) {
    for (const run of extra) nextCounts[run.status] = (nextCounts[run.status] ?? 0) + 1;
  }
  return { items: [...extra, ...listed], counts: nextCounts };
}

/** The runs this tab started of the flow, as `rememberStartedRun` keeps them. */
export function useStartedRuns(flowId: string): readonly StartedRun[] {
  const queryClient = useQueryClient();
  const key = startedRunsKey(flowId);
  const started = useQuery({
    queryKey: key,
    // Nothing to fetch: a refetch keeps what this tab remembered.
    queryFn: () => queryClient.getQueryData<StartedRun[]>(key) ?? [],
    staleTime: Infinity
  });
  return started.data ?? [];
}
