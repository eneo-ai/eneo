import type { FlowStep } from "@eneo/eneo-js";
import { getOutputModeCompatibilityIssue, mapOutputToInputType } from "./flowStepTypes";

/** Strip a client-only temporary step id (`_temp_…`) before persisting. */
export function stripTemporaryStepId(step: FlowStep): FlowStep {
  if (!step.id?.startsWith("_temp_")) return step;

  const stepWithoutTemporaryId: FlowStep = { ...step };
  delete stepWithoutTemporaryId.id;
  return stepWithoutTemporaryId;
}

export function isValidStepIndex(index: number, steps: FlowStep[]): boolean {
  return Number.isInteger(index) && index >= 0 && index < steps.length;
}

/** A stable identity key for a step that survives renames and reordering. */
export function getStableStepKey(step: FlowStep, index: number): string {
  if (step.id) return `id:${step.id}`;
  if (step.assistant_id) return `assistant:${step.assistant_id}`;
  return `index:${index}`;
}

/**
 * The blank/seeded step shape shared by appending (addStep) and inserting
 * (insertStepAfter). The input side is always derived from position so a seeded
 * step stays valid wherever it lands; the output side takes the seed's overrides,
 * falling back to a pass-through text step.
 *
 * A step that reads text and delivers Word or PDF can only set the text as it is:
 * an AI step cannot write the file itself. Such a seed therefore becomes the
 * no-AI document mode instead of a step the editor would immediately reject.
 */
export function buildBlankStep(params: {
  tempId: string;
  stepOrder: number;
  name: string;
  isFirst: boolean;
  prevStepOutputType?: FlowStep["output_type"];
  outputMode?: "pass_through";
  outputType?: FlowStep["output_type"];
}): Partial<FlowStep> & { id: string } {
  const inputType = params.isFirst ? "text" : mapOutputToInputType(params.prevStepOutputType);
  const outputType = params.outputType ?? "text";
  const requestedMode = params.outputMode ?? "pass_through";
  const needsVerbatimDocument =
    getOutputModeCompatibilityIssue({
      input_type: inputType,
      output_type: outputType,
      output_mode: requestedMode
    }) === "text_document_requires_render_verbatim";

  return {
    id: params.tempId,
    assistant_id: "",
    step_order: params.stepOrder,
    user_description: params.name,
    input_source: params.isFirst ? "flow_input" : "previous_step",
    input_type: inputType,
    output_mode: needsVerbatimDocument ? "render_verbatim" : requestedMode,
    output_type: outputType
  };
}
