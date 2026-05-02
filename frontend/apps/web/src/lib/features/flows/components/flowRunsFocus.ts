import { isFlowRunActive } from "./flowRunStatusSets";

type FocusableRun = {
  id: string;
  status: string;
};

export function getActiveFlowRunId(runs: FocusableRun[]): string | null {
  return runs.find((run) => isFlowRunActive(run.status))?.id ?? null;
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
  if (!activeRun || !isFlowRunActive(activeRun.status)) return false;

  if (selectedRunId === null) return true;
  if (selectedRunId === lastAutoFocusedRunId) return true;

  const selectedRun = runs.find((run) => run.id === selectedRunId);
  return selectedRun ? !isFlowRunActive(selectedRun.status) : true;
}
