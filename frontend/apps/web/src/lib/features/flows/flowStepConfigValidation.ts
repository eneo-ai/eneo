import type { FlowStep } from "@eneo/eneo-js";
import { hasDeletedInputBindingSourceRefs, getInputBindingQuestion } from "./flowInputBindings";
import { getTemplateFillOutputConfig } from "./templateFillConfig";
import { createDefaultHttpConfig } from "./components/http/httpConfigDefaults";
import { parseHttpAuthoredConfig } from "./components/http/httpConfigTypes";
import { getOutputModeCompatibilityIssue } from "./flowStepTypes";
import {
  getSpeakerMappingInferNames,
  getSpeakerMappingParticipantsField
} from "./speakerMappingConfig";

/** Matches the synthetic token for a reference to a since-deleted step. */
export const DELETED_STEP_TOKEN = /\{\{step_\d+_deleted/;

/**
 * Per-step configuration validation: a template_fill step needs a template
 * asset, and an HTTP input/output step needs a URL. Returned keys are namespaced
 * with `prefix` so the caller can replace exactly its own error slice.
 */
export function computeStepConfigValidationIssues(
  steps: FlowStep[],
  prefix: string
): Map<string, string[]> {
  const entries = new Map<string, string[]>();
  for (const step of steps) {
    if (getOutputModeCompatibilityIssue(step) !== null) {
      entries.set(`${prefix}output_mode_incompatible:${step.step_order}`, [
        "output_mode_incompatible"
      ]);
    }
    if (step.output_mode === "template_fill") {
      const config = getTemplateFillOutputConfig(step);
      if (!config.template_asset_id) {
        entries.set(`${prefix}template_fill_no_template:${step.step_order}`, [
          "template_fill_no_template"
        ]);
      } else {
        // A placeholder is mapped when it has an entry, even an explicit
        // empty one (a deliberate leave-empty choice); a placeholder without
        // an entry, or an entry for a placeholder the template no longer
        // has, is a known problem the publish check will reject.
        const placeholders = config.placeholders ?? [];
        const bindings = config.bindings ?? {};
        const mapped = (placeholder: string) =>
          Object.prototype.hasOwnProperty.call(bindings, placeholder);
        if (placeholders.some((placeholder) => !mapped(placeholder))) {
          entries.set(`${prefix}template_fill_missing_mappings:${step.step_order}`, [
            "template_fill_missing_mappings"
          ]);
        }
        if (Object.keys(bindings).some((name) => !placeholders.includes(name))) {
          entries.set(`${prefix}template_fill_orphaned_mappings:${step.step_order}`, [
            "template_fill_orphaned_mappings"
          ]);
        }
      }
    }
    // With name inference on, the conversation is the name source and a
    // participants field is optional.
    if (
      step.output_mode === "speaker_mapping" &&
      getSpeakerMappingParticipantsField(step) === null &&
      !getSpeakerMappingInferNames(step)
    ) {
      entries.set(`${prefix}speaker_mapping_no_participants_field:${step.step_order}`, [
        "speaker_mapping_no_participants_field"
      ]);
    }
    if (step.output_mode === "http_post") {
      const config = parseHttpAuthoredConfig(
        step.output_config,
        createDefaultHttpConfig("output", "POST")
      );
      if (!config.url.trim()) {
        entries.set(`${prefix}http_missing_url:${step.step_order}`, ["http_missing_url"]);
      }
    }
    if (step.input_source === "http_get") {
      const config = parseHttpAuthoredConfig(
        step.input_config,
        createDefaultHttpConfig("input", "GET")
      );
      if (!config.url.trim()) {
        entries.set(`${prefix}http_missing_url:${step.step_order}`, ["http_missing_url"]);
      }
    }
  }
  return entries;
}

/**
 * True if any step still references a deleted step — either in its
 * input_bindings.question or in its cached assistant prompt text. The caller
 * pre-fetches the cached prompt texts (keyed by assistant id) so this stays pure.
 */
export function hasDeletedStepReferences(
  steps: FlowStep[],
  cachedPromptTextByAssistantId: Map<string, string>
): boolean {
  for (const step of steps) {
    if (DELETED_STEP_TOKEN.test(getInputBindingQuestion(step.input_bindings))) {
      return true;
    }
    if (hasDeletedInputBindingSourceRefs(step.input_bindings)) return true;
    const text = cachedPromptTextByAssistantId.get(step.assistant_id) ?? "";
    if (DELETED_STEP_TOKEN.test(text)) return true;
  }
  return false;
}
