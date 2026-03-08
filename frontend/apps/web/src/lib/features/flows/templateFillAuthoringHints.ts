import type { FlowStep } from "@intric/intric-js";

export function shouldShowTemplateBodyTextHint(params: {
  steps: FlowStep[];
  activeStep: FlowStep | null | undefined;
  isAdvancedMode: boolean;
  isTemplateFill: boolean;
  isTranscribeOnly: boolean;
}): boolean {
  const { steps, activeStep, isAdvancedMode, isTemplateFill, isTranscribeOnly } = params;
  if (!isAdvancedMode || !activeStep || isTemplateFill || isTranscribeOnly) {
    return false;
  }

  return steps.some(
    (step) => step.output_mode === "template_fill" && step.step_order > activeStep.step_order
  );
}
