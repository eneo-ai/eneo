import type { FlowPublic, FlowStep } from "./editor/step-types";
import { stepLabel } from "./flow-labels";

/**
 * What changed between two readings of a flow, step by step: the chat's tools
 * change the draft while the page shows it, and the page marks the cards they
 * touched and says what they did. Pure and unit-tested.
 */

export type StepChange = "added" | "changed" | "moved";

export type FlowChanges = {
  /** The steps the flow has now that are new or different, by id. */
  steps: ReadonlyMap<string, StepChange>;
  /** The steps the flow no longer has. */
  removed: FlowStep[];
};

const NO_CHANGES: FlowChanges = { steps: new Map(), removed: [] };

/** A step's content apart from its place in the flow. */
function fingerprint(step: FlowStep): string {
  return JSON.stringify(step, (key, value: unknown) => (key === "step_order" ? undefined : value));
}

export function diffFlowSteps(before: Pick<FlowPublic, "steps">, after: Pick<FlowPublic, "steps">) {
  const earlier = new Map(
    before.steps.flatMap((step) => (step.id ? [[step.id, step] as const] : []))
  );
  const steps = new Map<string, StepChange>();
  for (const step of after.steps) {
    if (!step.id) continue;
    const was = earlier.get(step.id);
    if (!was) steps.set(step.id, "added");
    else if (fingerprint(was) !== fingerprint(step)) steps.set(step.id, "changed");
    else if (was.step_order !== step.step_order) steps.set(step.id, "moved");
    earlier.delete(step.id);
  }
  return steps.size === 0 && earlier.size === 0
    ? NO_CHANGES
    : { steps, removed: [...earlier.values()] };
}

export function hasChanges(changes: FlowChanges): boolean {
  return changes.steps.size > 0 || changes.removed.length > 0;
}

type Translate = (key: string, values?: Record<string, string | number>) => string;

/**
 * What the chat did, for the live region: "Chatten lade till Steg 3: Granska
 * svaret. Chatten ändrade Steg 2: Bedömning." Null when no step changed.
 */
export function describeChanges(
  changes: FlowChanges,
  after: Pick<FlowPublic, "steps">,
  t: Translate
): string | null {
  const sentences: string[] = [];
  for (const step of [...after.steps].sort((left, right) => left.step_order - right.step_order)) {
    const change = step.id ? changes.steps.get(step.id) : undefined;
    if (change) sentences.push(t(`flows_chat_changed_${change}`, { step: stepLabel(step, t) }));
  }
  for (const step of changes.removed) {
    sentences.push(t("flows_chat_changed_removed", { step: stepLabel(step, t) }));
  }
  return sentences.length > 0 ? sentences.join(" ") : null;
}
