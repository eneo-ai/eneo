import type { FlowEditDiff, StepChange, StepChangeKind, StepSpec } from "./protocol";

const ACTIONABLE_CHANGE_KINDS: StepChangeKind[] = ["added", "modified"];

export function getStepChangeKind(
  step: StepSpec,
  editDiff: FlowEditDiff | null | undefined
): StepChangeKind {
  if (!step.existing_step_ref) {
    return "added";
  }

  const matchingChange = editDiff?.step_changes.find(
    (change) => change.step_ref === step.existing_step_ref
  );
  return matchingChange?.kind ?? "unchanged";
}

export function getRemovedStepChanges(editDiff: FlowEditDiff | null | undefined): StepChange[] {
  return (editDiff?.step_changes ?? []).filter((change) => change.kind === "removed");
}

export function getFirstChangedStepIndex(
  steps: StepSpec[],
  editDiff: FlowEditDiff | null | undefined
): number | null {
  for (const [index, step] of steps.entries()) {
    if (ACTIONABLE_CHANGE_KINDS.includes(getStepChangeKind(step, editDiff))) {
      return index;
    }
  }
  return null;
}
