import type { FlowStep } from "@eneo/eneo-js";

/**
 * Pure boolean predicates for the auto-correcting guard effects in
 * FlowStepEditPanel. The effects stay in the component so Svelte tracks the
 * reactive reads; each effect calls its predicate synchronously and then
 * performs the same updateStep(...).
 */

/**
 * Detects a legacy authoring artifact: older builder versions could mirror the
 * assistant instruction into the input template. When an unpublished step still
 * carries that duplicate and it has not already been auto-cleared, clear it.
 */
export function shouldAutoClearLegacyTemplate(args: {
  stepId: string | null | undefined;
  isPublished: boolean;
  hasInputTemplateOverride: boolean;
  instructionText: string;
  inputTemplateText: string;
  alreadyAutoCleared: boolean;
}): boolean {
  return Boolean(
    args.stepId &&
    !args.isPublished &&
    args.hasInputTemplateOverride &&
    args.instructionText.trim().length > 0 &&
    args.inputTemplateText.trim() === args.instructionText.trim() &&
    !args.alreadyAutoCleared
  );
}

/**
 * transcribe_only steps only produce text; coerce a stale non-text output_type
 * back to "text".
 */
export function needsTranscribeOnlyOutputTypeCoercion(step: FlowStep): boolean {
  return step.output_mode === "transcribe_only" && step.output_type !== "text";
}

/**
 * transcribe_only requires an audio input; if the input type is no longer audio,
 * reset the output mode to pass_through.
 */
export function needsTranscribeOnlyOutputModeReset(step: FlowStep): boolean {
  return step.input_type !== "audio" && step.output_mode === "transcribe_only";
}
