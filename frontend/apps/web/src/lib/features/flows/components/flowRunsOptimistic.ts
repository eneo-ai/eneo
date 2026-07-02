import type { FlowRun } from "@eneo/eneo-js";

export function mergeOptimisticFlowRuns(runs: FlowRun[], optimisticRuns: FlowRun[]): FlowRun[] {
  if (optimisticRuns.length === 0) return runs;

  const existingIds = new Set(runs.map((run) => run.id));
  const missingRuns = optimisticRuns.filter((run) => !existingIds.has(run.id));

  return missingRuns.length > 0 ? [...missingRuns, ...runs] : runs;
}

export function getConfirmedOptimisticFlowRunIds(
  runs: FlowRun[],
  optimisticRuns: FlowRun[]
): string[] {
  if (optimisticRuns.length === 0 || runs.length === 0) return [];

  const existingIds = new Set(runs.map((run) => run.id));
  return optimisticRuns.filter((run) => existingIds.has(run.id)).map((run) => run.id);
}

export function shouldAutoFocusOptimisticFlowRun(
  newestOptimisticRun: FlowRun | undefined,
  lastAutoFocusedRunId: string | null
): newestOptimisticRun is FlowRun {
  return Boolean(newestOptimisticRun && newestOptimisticRun.id !== lastAutoFocusedRunId);
}
