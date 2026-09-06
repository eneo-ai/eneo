import type {
  FlowEditDiff,
  StepChange,
  StepChangeKind,
  StepFieldChange,
  StepSpec
} from "./protocol";

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

/** What the proposal changes in a published step; empty for new or untouched steps. */
export function getStepFieldChanges(
  step: StepSpec,
  editDiff: FlowEditDiff | null | undefined
): StepFieldChange[] {
  if (!step.existing_step_ref) return [];
  const matchingChange = editDiff?.step_changes.find(
    (change) => change.step_ref === step.existing_step_ref
  );
  return matchingChange?.kind === "modified" ? (matchingChange.field_changes ?? []) : [];
}

export function getRemovedStepChanges(editDiff: FlowEditDiff | null | undefined): StepChange[] {
  return (editDiff?.step_changes ?? []).filter((change) => change.kind === "removed");
}

export function getReviewFocusStepIndex(
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
