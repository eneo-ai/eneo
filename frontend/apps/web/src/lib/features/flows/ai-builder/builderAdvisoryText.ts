import { m } from "$lib/paraglide/messages";
import type { EditAdvisory, LintWarning } from "./protocol";

/**
 * The one owner of what the plan's advisories, quality warnings and notes say
 * to the reader. The server writes their prose for the model and for
 * diagnostics (mostly in English); the stable contract is the code, so the
 * screen reads each code in the reader's language and a code it does not
 * know yet as a calm generic sentence. The server's `message` is never shown,
 * and no value is mined out of it.
 */

const ADVISORY_COPY: Record<string, () => string> = {
  flow_description_update_required: () => m.ai_builder_advisory_flow_description_update_required(),
  mapped_file_limit_exceeds_policy: () => m.ai_builder_advisory_mapped_file_limit_exceeds_policy(),
  form_field_shadows_primary_input: () => m.ai_builder_advisory_form_field_shadows_primary_input(),
  input_source_all_previous_rewired: () =>
    m.ai_builder_advisory_input_source_all_previous_rewired(),
  duplicate_step_name_disambiguated: () =>
    m.ai_builder_advisory_duplicate_step_name_disambiguated(),
  pre_terminal_artifact_body_step_renamed: () =>
    m.ai_builder_advisory_pre_terminal_artifact_body_step_renamed(),
  output_mode_template_fill_reset: () => m.ai_builder_advisory_output_mode_template_fill_reset(),
  output_config_template_fill_keys_cleared: () =>
    m.ai_builder_advisory_output_config_template_fill_keys_cleared(),
  source_refs_deduped: () => m.ai_builder_advisory_source_refs_deduped(),
  explicit_question_input_contract_cleared: () =>
    m.ai_builder_advisory_explicit_question_input_contract_cleared(),
  all_previous_input_contract_cleared: () =>
    m.ai_builder_advisory_all_previous_input_contract_cleared(),
  document_renderer_must_immediately_follow_body_writer: () =>
    m.ai_builder_advisory_document_renderer_must_immediately_follow_body_writer(),
  terminal_renderer_must_not_consume_review_only_step: () =>
    m.ai_builder_advisory_terminal_renderer_must_not_consume_review_only_step(),
  citation_mode_unsupported: () => m.flow_validation_msg_citation_mode_unsupported()
};

export function advisoryText(advisory: Pick<EditAdvisory, "code" | "message">): string {
  return (ADVISORY_COPY[advisory.code] ?? m.ai_builder_advisory_generic)();
}

// Fields that name the flow rather than one of its steps.
const FLOW_LEVEL_FIELDS: ReadonlySet<string> = new Set([
  "steps",
  "form_fields",
  "flow_description"
]);

/** The step reference a field-scoped advisory is about ("step_b.input_source"
 *  is about step_b), or null for a flow-level field. The screen resolves the
 *  reference against the plan; one it cannot resolve names no step. */
export function advisoryStepRef(advisory: Pick<EditAdvisory, "field">): string | null {
  const field = advisory.field ?? "";
  const dot = field.indexOf(".");
  const head = dot === -1 ? field : field.slice(0, dot);
  if (!head || dot === -1 || FLOW_LEVEL_FIELDS.has(head)) return null;
  return head;
}

type LintCopy = (fieldName: string | null) => string;

const LINT_WARNING_COPY: Record<string, LintCopy> = {
  source_contract_shadow_form_field_dropped: (field) =>
    field
      ? m.ai_builder_lint_source_contract_shadow_form_field_dropped_named({ field })
      : m.ai_builder_lint_source_contract_shadow_form_field_dropped(),
  primary_input_shadow_form_field_dropped: (field) =>
    field
      ? m.ai_builder_lint_primary_input_shadow_form_field_dropped_named({ field })
      : m.ai_builder_lint_primary_input_shadow_form_field_dropped(),
  citation_mode_unsupported: () => m.flow_validation_msg_citation_mode_unsupported()
};

/** A quality warning that asks for attention before approval. */
export function lintWarningText(
  warning: Pick<LintWarning, "code" | "message"> & { field_name?: string | null }
): string {
  const copy = LINT_WARNING_COPY[warning.code];
  if (!copy) return m.ai_builder_lint_generic();
  const field = warning.field_name?.trim() || null;
  return copy(field);
}

// INFO entries are facts about the flow as it already was (a pre-existing gap
// on a step this edit did not touch): they read as information, never as work.
const FLOW_NOTE_COPY: Record<string, () => string> = {
  json_output_no_contract: () => m.ai_builder_flow_note_json_output_no_contract(),
  json_output_text_interpolation: () => m.ai_builder_flow_note_json_output_text_interpolation(),
  shadowed_form_field_bare_reference: () =>
    m.ai_builder_flow_note_shadowed_form_field_bare_reference(),
  unused_form_field: () => m.ai_builder_flow_note_unused_form_field(),
  vague_step_name: () => m.ai_builder_flow_note_vague_step_name()
};

export function flowNoteText(note: { code: string }): string {
  return (FLOW_NOTE_COPY[note.code] ?? m.ai_builder_flow_note_generic)();
}
