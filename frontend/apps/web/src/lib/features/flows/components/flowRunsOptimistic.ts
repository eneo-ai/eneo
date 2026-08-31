import type { FlowRun, FlowRunSummary } from "@eneo/eneo-js";

export function mergeOptimisticFlowRuns(
  runs: FlowRunSummary[],
  optimisticRuns: FlowRun[]
): FlowRunSummary[] {
  if (optimisticRuns.length === 0) return runs;

  const existingIds = new Set(runs.map((run) => run.id));
  const missingRuns = optimisticRuns.filter((run) => !existingIds.has(run.id));

  return missingRuns.length > 0 ? [...missingRuns, ...runs] : runs;
}

export function getConfirmedOptimisticFlowRunIds(
  runs: FlowRunSummary[],
  optimisticRuns: FlowRun[]
): string[] {
  if (optimisticRuns.length === 0 || runs.length === 0) return [];

  const existingIds = new Set(runs.map((run) => run.id));
  return optimisticRuns.filter((run) => existingIds.has(run.id)).map((run) => run.id);
}
