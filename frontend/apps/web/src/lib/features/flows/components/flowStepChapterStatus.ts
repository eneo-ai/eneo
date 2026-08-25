import type { FlowStep, SecurityClassification } from "@eneo/eneo-js";
import { m } from "$lib/paraglide/messages";
import { OUTPUT_MODES } from "$lib/features/flows/flowStepTypes";
import {
  getEnkelAwareOutputTypeLabel,
  getOutputTypeLabel,
  getSecurityClassificationLabel
} from "./flowStepEditHelpers";

/**
 * Short status labels shown on the collapsed chapter headers of the step
 * editor. Each is a pure function of the active step so the header text and
 * the expanded controls read from one source and cannot drift.
 */

function getOutputTypeDisplay(step: FlowStep, isAdvancedMode: boolean): string {
  return getEnkelAwareOutputTypeLabel(
    step.output_type,
    getOutputTypeLabel(step.output_type),
    isAdvancedMode
  );
}

export function getChapterOutputStatus(step: FlowStep, isAdvancedMode = true): string {
  const modeLabel = OUTPUT_MODES.find((option) => option.value === step.output_mode)?.label ?? "";
  const outputLabel = getOutputTypeDisplay(step, isAdvancedMode);
  return modeLabel ? `${outputLabel} · ${modeLabel}` : outputLabel;
}

export function getChapterControlStatus(
  step: FlowStep,
  inheritedClassification?: Pick<SecurityClassification, "name" | "security_level"> | null,
  availableClassifications: Pick<SecurityClassification, "name" | "security_level">[] = []
): string {
  const reviewLabel =
    step.review_policy?.mode === "view"
      ? m.flow_step_review_policy_view()
      : step.review_policy?.mode === "edit"
        ? m.flow_step_review_policy_edit()
        : m.flow_step_review_policy_none();
  const explicitClassification = availableClassifications.find(
    (classification) => classification.security_level === step.output_classification_override
  );
  const securityLabel =
    step.output_classification_override == null
      ? inheritedClassification
        ? `${getSecurityClassificationLabel(inheritedClassification)} (${m.flow_step_security_inherit()})`
        : m.flow_step_security_inherit_summary()
      : explicitClassification
        ? getSecurityClassificationLabel(explicitClassification)
        : m.flow_step_legacy_invalid_option();
  return `${reviewLabel} · ${securityLabel}`;
}

export function getChapterTaskStatus(
  step: Pick<FlowStep, "user_description">,
  instructionText: string,
  fallback: string
): string {
  const instruction = instructionText.replace(/\s+/g, " ").trim();
  return instruction || fallback || step.user_description || "";
}

export function getChapterInputStatus({
  step,
  previousStep,
  hasKnowledge,
  hasAttachments
}: {
  step: Pick<FlowStep, "input_source" | "step_order">;
  previousStep?: Pick<FlowStep, "step_order" | "user_description"> | null;
  hasKnowledge: boolean;
  hasAttachments: boolean;
}): string {
  const source =
    step.input_source === "previous_step" && previousStep
      ? `${m.flow_input_template_effective_step({ step: previousStep.step_order })}${
          previousStep.user_description ? `: ${previousStep.user_description}` : ""
        }`
      : step.input_source === "all_previous_steps"
        ? m.flow_input_source_all_previous_steps()
        : step.input_source === "http_get"
          ? m.flow_input_source_http_get()
          : m.flow_input_source_flow_input();
  const extra =
    hasKnowledge || hasAttachments
      ? m.flow_chapter_input_extra_active()
      : m.flow_chapter_input_extra_none();
  return `${source} · ${extra}`;
}

export function getTechnicalSettingsCount(step: FlowStep): number {
  return [
    step.input_contract,
    step.output_contract,
    step.input_source === "http_get" ? step.input_config : null,
    step.output_mode === "http_post" ? step.output_config : null,
    // Template binding lives in the advanced chapter; without counting it,
    // an AI-built template flow is a dead end in Enkel (no bridge appears).
    step.output_mode === "template_fill" ? step : null
  ].filter((value) => value != null).length;
}

export function getChapterAdvancedStatus(step: FlowStep): string {
  const settings = [
    step.input_contract != null ? m.flow_technical_input_contract_active() : null,
    step.output_contract != null ? m.flow_technical_output_contract_active() : null,
    step.input_source === "http_get" ? m.flow_technical_http_input_active() : null,
    step.output_mode === "http_post" ? m.flow_technical_http_output_active() : null
  ].filter((value) => value !== null);
  return settings.join(" · ") || m.flow_chapter_advanced_default();
}
