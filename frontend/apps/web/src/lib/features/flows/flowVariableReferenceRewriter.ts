import type { FlowStep } from "@eneo/eneo-js";

/**
 * Rewrite each step's `input_bindings.question` with `rewriteQuestion`, keeping
 * reference identity for steps that are skipped, have no question, or are left
 * unchanged. The form-field-rename and step-rename reference migrations share
 * this walk and differ only in their token-replacement function and which steps
 * they touch (`shouldSkip`).
 */
export function rewriteStepBindings(
  steps: FlowStep[],
  rewriteQuestion: (question: string) => string,
  shouldSkip?: (step: FlowStep) => boolean
): FlowStep[] {
  return steps.map((step) => {
    if (shouldSkip?.(step)) return step;
    const bindings = (step.input_bindings as Record<string, unknown> | null | undefined) ?? null;
    const question = typeof bindings?.question === "string" ? bindings.question : null;
    if (!question) return step;
    const rewritten = rewriteQuestion(question);
    if (rewritten === question) return step;
    return {
      ...step,
      input_bindings: { ...(bindings ?? {}), question: rewritten }
    };
  });
}
