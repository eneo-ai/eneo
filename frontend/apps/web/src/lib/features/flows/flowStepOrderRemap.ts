import type { FlowStep } from "@eneo/eneo-js";
import { remapInputBindingSourceRefs } from "./flowInputBindings";
import { getStableStepKey } from "./flowStepPayloadShaping";
import { remapStepOrderTemplateTokens } from "./flowVariableTokens";

export interface StepOrderRemapResult {
  /** `nextSteps` with each step's binding tokens remapped to the new orders. */
  rewrittenSteps: FlowStep[];
  /** Old step_order -> new step_order for steps that survived the change. */
  remapByOldOrder: Map<number, number>;
  /** step_orders present before the change but gone after it. */
  deletedOrders: Set<number>;
  /** Deleted orders that were still referenced by a step's input bindings. */
  impactedDeletedBindingOrders: Set<number>;
}

/**
 * Pure computation behind a safe step reorder/removal: match steps by stable
 * identity to learn how orders moved, find which orders disappeared, and rewrite
 * step-order references inside each step's `input_bindings.question` and
 * `input_bindings.source_refs`. The caller owns applying the result to the store
 * and remapping the assistant prompts.
 */
export function computeStepOrderRemap(
  previousSteps: FlowStep[],
  nextSteps: FlowStep[]
): StepOrderRemapResult {
  const previousOrderByKey = new Map<string, number>();
  for (let i = 0; i < previousSteps.length; i += 1) {
    const step = previousSteps[i];
    previousOrderByKey.set(getStableStepKey(step, i), step.step_order);
  }

  const remapByOldOrder = new Map<number, number>();
  const seenOldOrders = new Set<number>();
  const rewrittenSteps = nextSteps.map((step, index) => {
    const key = getStableStepKey(step, index);
    const oldOrder = previousOrderByKey.get(key);
    if (oldOrder !== undefined) {
      remapByOldOrder.set(oldOrder, step.step_order);
      seenOldOrders.add(oldOrder);
    }
    return { ...step };
  });

  const deletedOrders = new Set<number>();
  for (const previousStep of previousSteps) {
    if (!seenOldOrders.has(previousStep.step_order)) {
      deletedOrders.add(previousStep.step_order);
    }
  }

  const impactedDeletedBindingOrders = new Set<number>();
  for (let i = 0; i < rewrittenSteps.length; i += 1) {
    const step = rewrittenSteps[i];
    const bindings = (step.input_bindings as Record<string, unknown> | null | undefined) ?? null;
    const question = typeof bindings?.question === "string" ? bindings.question : null;
    if (question) {
      const remapped = remapStepOrderTemplateTokens(question, remapByOldOrder, deletedOrders);
      if (remapped.changed) {
        rewrittenSteps[i] = {
          ...step,
          input_bindings: { ...(bindings ?? {}), question: remapped.text }
        };
      }
      for (const deletedReference of remapped.rewrittenDeletedReferences) {
        impactedDeletedBindingOrders.add(deletedReference);
      }
    }

    const sourceRefsRemap = remapInputBindingSourceRefs(
      rewrittenSteps[i].input_bindings,
      remapByOldOrder,
      deletedOrders
    );
    if (sourceRefsRemap.changed) {
      rewrittenSteps[i] = {
        ...rewrittenSteps[i],
        input_bindings: sourceRefsRemap.inputBindings
      };
    }
    for (const deletedReference of sourceRefsRemap.rewrittenDeletedReferences) {
      impactedDeletedBindingOrders.add(deletedReference);
    }
  }

  return { rewrittenSteps, remapByOldOrder, deletedOrders, impactedDeletedBindingOrders };
}
