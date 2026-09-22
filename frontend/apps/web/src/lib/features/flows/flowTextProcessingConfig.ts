import type { FlowStep } from "@eneo/eneo-js";

/**
 * Owner of `input_config.text_processing` in the editor: how a step reads its
 * material. `null` is the default (everything at once). The runtime accepts
 * a mode only on a pass_through completion step with JSON output that is not
 * already mapped per source or per item (step_mapped_execution.py).
 */
export type FlowTextProcessingMode = "process_each_section" | "summarize";

export type FlowSectionProcessingEligibility = {
  eligible: boolean;
  reason: "output" | "mapped" | null;
};

type TextProcessingStepLike = Pick<FlowStep, "input_config"> &
  Partial<Pick<FlowStep, "output_mode" | "output_type">>;

function asObject(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  return value as Record<string, unknown>;
}

export function getTextProcessingMode(
  step: Pick<FlowStep, "input_config">
): FlowTextProcessingMode | null {
  const mode = asObject(asObject(step.input_config)?.text_processing)?.mode;
  return mode === "process_each_section" || mode === "summarize" ? mode : null;
}

export function getSectionProcessingEligibility(
  step: TextProcessingStepLike
): FlowSectionProcessingEligibility {
  if (step.output_mode !== "pass_through" || step.output_type !== "json") {
    return { eligible: false, reason: "output" };
  }
  const inputConfig = asObject(step.input_config);
  const runtimeInput = asObject(inputConfig?.runtime_input);
  const itemMap = asObject(inputConfig?.item_map);
  if (
    (runtimeInput?.enabled === true && runtimeInput.execution_mode === "per_source") ||
    itemMap?.enabled === true
  ) {
    return { eligible: false, reason: "mapped" };
  }
  return { eligible: true, reason: null };
}

export function updateTextProcessingMode(
  step: Pick<FlowStep, "input_config">,
  mode: FlowTextProcessingMode | null
): Record<string, unknown> {
  const inputConfig = { ...(asObject(step.input_config) ?? {}) };
  if (mode === null) {
    delete inputConfig.text_processing;
  } else {
    inputConfig.text_processing = { mode };
  }
  return inputConfig;
}
