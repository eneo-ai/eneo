import type { FlowStep } from "@eneo/eneo-js";
import { outputModeUsesCompletionModel } from "./flowStepTypes";

export const FLOW_CITATION_MODE_OFF = "off" as const;
export const FLOW_CITATION_MODE_INLINE_INREF_SIDECAR = "inline_inref_sidecar" as const;

export type FlowCitationMode =
  typeof FLOW_CITATION_MODE_OFF | typeof FLOW_CITATION_MODE_INLINE_INREF_SIDECAR;

type OutputConfigValue = FlowStep["output_config"];

function asOutputConfigRecord(outputConfig: OutputConfigValue): Record<string, unknown> {
  if (!outputConfig || typeof outputConfig !== "object" || Array.isArray(outputConfig)) {
    return {};
  }
  return { ...outputConfig };
}

export function resolveFlowCitationMode(outputConfig: OutputConfigValue): FlowCitationMode {
  const rawMode = asOutputConfigRecord(outputConfig).citation_mode;
  return rawMode === FLOW_CITATION_MODE_INLINE_INREF_SIDECAR
    ? FLOW_CITATION_MODE_INLINE_INREF_SIDECAR
    : FLOW_CITATION_MODE_OFF;
}

/**
 * Source references attach to text an AI model wrote. A step that only passes text
 * on, transcribes or renders a document has no model answer to reference, and the
 * server refuses the setting there (`is_citation_capable_step`).
 */
export function supportsFlowCitationMode(
  step: Pick<FlowStep, "output_type" | "output_mode"> | null | undefined
): boolean {
  return Boolean(
    step && step.output_type === "text" && outputModeUsesCompletionModel(step.output_mode)
  );
}

export function setFlowCitationMode(
  outputConfig: OutputConfigValue,
  citationMode: FlowCitationMode
): OutputConfigValue {
  const nextConfig = asOutputConfigRecord(outputConfig);
  if (citationMode === FLOW_CITATION_MODE_INLINE_INREF_SIDECAR) {
    nextConfig.citation_mode = FLOW_CITATION_MODE_INLINE_INREF_SIDECAR;
  } else {
    delete nextConfig.citation_mode;
  }
  return Object.keys(nextConfig).length > 0 ? nextConfig : null;
}

export function preserveFlowCitationMode(
  nextOutputConfig: OutputConfigValue,
  currentOutputConfig: OutputConfigValue
): OutputConfigValue {
  return setFlowCitationMode(nextOutputConfig, resolveFlowCitationMode(currentOutputConfig));
}

export function sanitizeStepCitationMode(step: FlowStep): FlowStep {
  if (supportsFlowCitationMode(step)) {
    return step;
  }
  const nextOutputConfig = setFlowCitationMode(step.output_config, FLOW_CITATION_MODE_OFF);
  return nextOutputConfig === step.output_config
    ? step
    : {
        ...step,
        output_config: nextOutputConfig
      };
}

export function hasAdvancedOutputConfig(
  step: Pick<FlowStep, "output_config" | "output_mode">
): boolean {
  if (
    !step.output_config ||
    typeof step.output_config !== "object" ||
    Array.isArray(step.output_config)
  ) {
    return false;
  }
  const nextConfig = { ...step.output_config };
  delete nextConfig.citation_mode;
  return Object.keys(nextConfig).length > 0;
}
