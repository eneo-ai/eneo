import type { FlowStep } from "@eneo/eneo-js";
import { m } from "$lib/paraglide/messages";
import { OUTPUT_MODES } from "$lib/features/flows/flowStepTypes";
import { getInputTypeLabel, getOutputTypeLabel } from "./flowStepEditHelpers";

/**
 * Short status labels shown on the collapsed chapter headers of the step
 * editor. Each is a pure function of the active step so the header text and
 * the expanded controls read from one source and cannot drift.
 */

export function getChapterWhatStatus(step: FlowStep): string {
  return `${getInputTypeLabel(step.input_type)} → ${getOutputTypeLabel(step.output_type)}`;
}

export function getChapterOutputStatus(step: FlowStep): string {
  const modeLabel = OUTPUT_MODES.find((option) => option.value === step.output_mode)?.label ?? "";
  const outputLabel = getOutputTypeLabel(step.output_type);
  return modeLabel ? `${outputLabel} · ${modeLabel}` : outputLabel;
}

export function getChapterControlStatus(step: FlowStep): string {
  return step.output_classification_override == null
    ? m.flow_step_security_inherit()
    : `K${step.output_classification_override}`;
}

export function getChapterAdvancedStatus(step: FlowStep): string {
  return step.input_contract != null || step.output_contract != null
    ? m.flow_chapter_advanced_custom()
    : m.flow_chapter_advanced_default();
}
