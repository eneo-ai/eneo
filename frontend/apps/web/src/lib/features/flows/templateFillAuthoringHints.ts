import type { FlowStep } from "@eneo/eneo-js";

export function shouldShowTemplateBodyTextHint(params: {
  steps: FlowStep[];
  activeStep: FlowStep | null | undefined;
  isTemplateFill: boolean;
  isTranscribeOnly: boolean;
}): boolean {
  // The template can only bind to a named step, so the hint shows in both
  // modes whenever a later template step depends on this one.
  const { steps, activeStep, isTemplateFill, isTranscribeOnly } = params;
  if (!activeStep || isTemplateFill || isTranscribeOnly) {
    return false;
  }

  return steps.some(
    (step) => step.output_mode === "template_fill" && step.step_order > activeStep.step_order
  );
}

export function shouldShowTemplateAccessibilityHint(params: { isTemplateFill: boolean }): boolean {
  // Accessible templates are a legal requirement for public-sector output,
  // so the warning shows in both modes.
  return params.isTemplateFill;
}
