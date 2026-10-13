import type { FlowStep } from "@eneo/eneo-js";
import { rewriteBoundToolArguments } from "./components/tool/toolInputConfig";

/**
 * Rewrite each step's `input_bindings.question` and, on a tool step, each
 * argument that is one whole variable, with `rewriteReferences`, keeping
 * reference identity for steps that are skipped or left unchanged. The
 * form-field-rename and step-rename reference migrations share this walk and
 * differ only in their token-replacement function and which steps they touch
 * (`shouldSkip`).
 */
export function rewriteStepBindings(
  steps: FlowStep[],
  rewriteReferences: (text: string) => string,
  shouldSkip?: (step: FlowStep) => boolean
): FlowStep[] {
  return steps.map((original) => {
    if (shouldSkip?.(original)) return original;
    const step = rewriteBoundToolArguments(original, rewriteReferences);
    const bindings = (step.input_bindings as Record<string, unknown> | null | undefined) ?? null;
    const question = typeof bindings?.question === "string" ? bindings.question : null;
    if (!question) return step;
    const rewritten = rewriteReferences(question);
    if (rewritten === question) return step;
    return {
      ...step,
      input_bindings: { ...(bindings ?? {}), question: rewritten }
    };
  });
}
