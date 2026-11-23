/**
 * Which steps of a flow are its run's deliverables: the core's rule
 * (`deliverable_positions` in `domain/run_deliverables.py`), so the editor
 * shows what publishing and the run will choose. Pure and unit-tested against
 * the core's own table.
 */
import { readDeliverable, sendsRunResult, stepCanBeDeliverable } from "./editor/step-configs";
import type { OutputMode, OutputType } from "./editor/step-types";

/** What the rule reads of a step. */
type DeliverableFacts = {
  step_order: number;
  output_type: OutputType;
  output_mode: OutputMode;
  output_config?: unknown;
};

/** Where a step stands that is a deliverable by its place alone. */
export type DeliverablePlace = "last" | "before_send";

export type RunDeliverables<S> = {
  /** The steps the run delivers, in step order. */
  deliverables: S[];
  /**
   * The step that is delivered by its place, marked or not: the last step,
   * or the one right before a last step that sends the run's result.
   */
  byPlace: { step: S; place: DeliverablePlace } | null;
  /** Steps that could be delivered but are not, in step order. */
  candidates: S[];
  /** The last step, when it sends the run's result. */
  sender: S | null;
};

export function isMarkedDeliverable(step: { output_config?: unknown }): boolean {
  return readDeliverable(step.output_config) !== null;
}

/**
 * Each marked step and the last step are delivered when their text or
 * document can be. A last step that sends the run's result holds nothing of
 * its own, so the step before it stands in its place.
 */
export function flowDeliverables<S extends DeliverableFacts>(
  steps: readonly S[]
): RunDeliverables<S> {
  const ordered = [...steps].sort((left, right) => left.step_order - right.step_order);
  const final = ordered.at(-1);
  const sender = final && sendsRunResult(final) ? final : null;
  const last = ordered.length - (sender ? 2 : 1);
  const placed = ordered[last];
  const byPlace =
    placed && stepCanBeDeliverable(placed)
      ? { step: placed, place: sender ? ("before_send" as const) : ("last" as const) }
      : null;
  const deliverables: S[] = [];
  const candidates: S[] = [];
  ordered.forEach((step, position) => {
    if (step === sender || !stepCanBeDeliverable(step)) return;
    if (isMarkedDeliverable(step) || position === last) deliverables.push(step);
    else candidates.push(step);
  });
  return { deliverables, byPlace, candidates, sender };
}
