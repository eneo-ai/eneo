import type { FlowStep } from "@eneo/eneo-js";
import { hasDeletedInputBindingSourceRefs, getInputBindingQuestion } from "./flowInputBindings";
import { getTemplateFillOutputConfig, isStructuredTemplateBinding } from "./templateFillConfig";
import { createDefaultHttpConfig } from "./components/http/httpConfigDefaults";
import { parseHttpAuthoredConfig } from "./components/http/httpConfigTypes";
import {
  boundToolArguments,
  findToolOption,
  lacksChosenTool,
  readToolInputConfig,
  type ArgumentsScope,
  type FlowToolOption
} from "./components/tool/toolInputConfig";
import { missingRequiredArguments } from "./components/tool/toolInputSchema";
import type { StepFocusTarget } from "./flowStepFocus";
import { getOutputModeCompatibilityIssue } from "./flowStepTypes";
import {
  getSpeakerMappingInferNames,
  getSpeakerMappingParticipantsField
} from "./speakerMappingConfig";

/** Matches the synthetic token for a reference to a since-deleted step. */
export const DELETED_STEP_TOKEN = /\{\{step_\d+_deleted/;

const TOOL_MISSING_TOOL = "tool_missing_tool";
const TOOL_ARGUMENT_MISSING = "tool_argument_missing";
const TOOL_ARGUMENTS_UNSAVED = "tool_arguments_unsaved";

/**
 * Where the author fixes an issue of a tool step this module reports: the
 * picker, or the first argument the issue names. A text that is not saved
 * names the argument of its row, and none when it is in the JSON field.
 * Null for every other issue.
 */
export function configIssueFocusTarget(
  code: string,
  subjects: readonly string[]
): StepFocusTarget | null {
  if (code === TOOL_MISSING_TOOL) return { kind: "tool" };
  const [first] = subjects;
  if (code === TOOL_ARGUMENTS_UNSAVED) {
    return first === undefined
      ? { kind: "tool_arguments" }
      : { kind: "tool_argument", name: first };
  }
  if (code === TOOL_ARGUMENT_MISSING && first) return { kind: "tool_argument", name: first };
  return null;
}

/**
 * Per-step configuration validation: a template_fill step needs a template
 * asset, an HTTP input/output step needs a URL, and a tool input step needs a
 * chosen tool, a value for each argument the tool requires, and no arguments
 * text the step cannot hold in the fields `unsavedArguments` reports. What a tool
 * requires is known only once `toolOptions` are. Returned keys are namespaced
 * with `prefix` so the caller can replace exactly its own error slice.
 */
export function computeStepConfigValidationIssues(
  steps: FlowStep[],
  prefix: string,
  toolOptions: FlowToolOption[] | null = null,
  unsavedArguments: (step: FlowStep) => readonly ArgumentsScope[] = () => []
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
        if (Object.values(config.bindings ?? {}).some(isStructuredTemplateBinding)) {
          entries.set(`${prefix}template_fill_structured_mapping:${step.step_order}`, [
            "template_fill_structured_mapping"
          ]);
        }
        // The placeholder inventory is optional draft metadata: the Builder
        // omits it and publication inspects the DOCX itself. Diagnostics are
        // only possible against a known inventory. A placeholder is mapped
        // when it has an entry, even an explicit empty one (a deliberate
        // leave-empty choice); a placeholder without an entry, or an entry
        // for a placeholder the template no longer has, is a known problem.
        const placeholders = config.placeholders;
        if (Array.isArray(placeholders)) {
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
    const unsaved = step.input_source === "tool" ? unsavedArguments(step) : [];
    if (unsaved.length > 0) {
      // The rows' arguments first, so "Go to step" lands on one; the JSON
      // field has none.
      entries.set(`${prefix}${TOOL_ARGUMENTS_UNSAVED}:${step.step_order}`, [
        TOOL_ARGUMENTS_UNSAVED,
        ...unsaved.flatMap((scope) => ("only" in scope ? [scope.only] : []))
      ]);
    }
    if (lacksChosenTool(step)) {
      entries.set(`${prefix}${TOOL_MISSING_TOOL}:${step.step_order}`, [TOOL_MISSING_TOOL]);
    } else if (step.input_source === "tool" && toolOptions) {
      const tool = readToolInputConfig(step.input_config);
      const option = findToolOption(toolOptions, tool);
      const missing =
        tool && option ? missingRequiredArguments(option.input_schema, tool.arguments) : [];
      if (missing.length > 0) {
        // The values after the code are what the issue is about: the banner names them.
        entries.set(`${prefix}${TOOL_ARGUMENT_MISSING}:${step.step_order}`, [
          TOOL_ARGUMENT_MISSING,
          ...missing
        ]);
      }
    }
  }
  return entries;
}

/**
 * True if any step still references a deleted step — in its
 * input_bindings.question, in a bound argument of its tool or in its cached
 * assistant prompt text. The caller
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
    if (boundToolArguments(step).some((reference) => DELETED_STEP_TOKEN.test(reference))) {
      return true;
    }
    const text = cachedPromptTextByAssistantId.get(step.assistant_id) ?? "";
    if (DELETED_STEP_TOKEN.test(text)) return true;
  }
  return false;
}
