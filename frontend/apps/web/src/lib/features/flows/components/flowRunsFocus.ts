type FocusableRun = {
  id: string;
  status: string;
};

const ACTIVE_RUN_STATUSES = new Set(["queued", "running"]);

export function getActiveFlowRunId(runs: FocusableRun[]): string | null {
  return runs.find((run) => ACTIVE_RUN_STATUSES.has(run.status))?.id ?? null;
}

export function shouldAutoFocusFlowRun({
  runs,
  activeRunId,
  selectedRunId,
  lastAutoFocusedRunId
}: {
  runs: FocusableRun[];
  activeRunId: string;
  selectedRunId: string | null;
  lastAutoFocusedRunId: string | null;
}): boolean {
  const activeRun = runs.find((run) => run.id === activeRunId);
  if (!activeRun || !ACTIVE_RUN_STATUSES.has(activeRun.status)) return false;

  if (selectedRunId === null) return true;
  if (selectedRunId === lastAutoFocusedRunId) return true;

  const selectedRun = runs.find((run) => run.id === selectedRunId);
  return selectedRun ? !ACTIVE_RUN_STATUSES.has(selectedRun.status) : true;
}
