import type { ReadMeaning } from "./request-preview";
import type { ReviewChoice } from "./step-configs";
import type { ChainIssue, OutputModeIssue } from "./step-rules";
import type { FlowPublic, InputSource, InputType, OutputMode, OutputType } from "./step-types";
import type { VariableEntry, VariableGroup } from "./step-variables";

/**
 * Reader-facing names for the core's step values. The enum names reuse the
 * reference editor's wording (apps/web catalog), so a step reads the same in
 * both apps; what is web-next's own carries the `flow_step_editor_` prefix.
 */

type T = (key: string, values?: Record<string, string | number>) => string;

export function inputSourceLabel(source: InputSource, t: T): string {
  return t(`flow_input_source_${source}`);
}

export function inputTypeLabel(type: InputType, t: T): string {
  return t(`flow_type_${type}`);
}

export function outputModeLabel(mode: OutputMode, t: T): string {
  return t(`flow_output_mode_${mode}`);
}

export function outputTypeLabel(type: OutputType, t: T): string {
  return t(`flow_output_type_${type}`);
}

export function reviewChoiceLabel(choice: ReviewChoice, t: T): string {
  return t(`flow_step_review_policy_${choice}`);
}

/** The reference wording for a stored value that is no longer a valid choice here. */
export function invalidOptionLabel(label: string, t: T): string {
  return t("flow_step_option_invalid", { label });
}

export function outputModeIssueText(issue: OutputModeIssue, t: T): string {
  switch (issue) {
    case "copy_input_requires_json":
      return t("flow_output_mode_invalid_copy_input");
    case "compose_text_requires_text":
      return t("flow_output_mode_invalid_compose_text");
    case "render_verbatim_requires_text_document":
      return t("flow_output_mode_invalid_render_verbatim");
    case "template_fill_requires_docx":
      return t("flow_output_mode_invalid_template_fill");
    case "transcribe_only_requires_audio_text":
      return t("flow_output_mode_invalid_transcribe_only");
    case "speaker_mapping_requires_text_json":
      return t("flow_output_mode_invalid_speaker_mapping");
    case "text_document_requires_render_verbatim":
      return t("flow_output_mode_invalid_text_document");
    case "http_post_must_be_last":
      return t("flow_step_editor_http_post_must_be_last");
  }
}

export function chainIssueText(issue: ChainIssue, t: T): string {
  switch (issue) {
    case "flow_input_not_first":
      return t("flow_step_editor_chain_flow_input_not_first");
    case "previous_on_first":
      return t("flow_step_editor_chain_previous_on_first");
    case "file_type_needs_flow_input":
      return t("flow_step_editor_chain_file_type_needs_flow_input");
    case "json_from_all_previous":
      return t("flow_step_editor_chain_json_from_all_previous");
    case "outside_source_with_underlag":
      return t("flow_step_editor_chain_outside_source_with_underlag");
    case "incompatible_previous":
      return t("flow_step_editor_chain_incompatible_previous");
    case "image_unsupported":
      return t("flow_step_editor_chain_image_unsupported");
  }
}

/** "Steg 2 · Sammanfatta", or "Steg 2" for an unnamed step. */
export function stepLabel(order: number, name: string | null | undefined, t: T): string {
  const trimmed = name?.trim();
  return trimmed
    ? t("flow_step_editor_step_named", { order, name: trimmed })
    : t("flow_step_editor_step_number", { order });
}

/**
 * What a reference reads, as its pill names it wherever it shows: the step as
 * a step card heads it, then what of it ("Steg 1: Extrahera › fastighet").
 */
export function meaningLabel(
  meaning: ReadMeaning,
  token: string,
  flow: Pick<FlowPublic, "steps">,
  t: T
): string {
  const step = (order: number) =>
    stepLabel(order, flow.steps.find((item) => item.step_order === order)?.user_description, t);
  switch (meaning.kind) {
    case "form_field":
      return meaning.label;
    case "flow_input":
      return t("flow_editor_tools_preview_read_flow_input");
    case "upload":
      return t("flow_step_editor_variable_upload");
    case "transcription":
      return t("flow_step_editor_variable_transcription");
    case "date":
      return t("flow_step_editor_variable_date");
    case "section_index":
      return t("flow_step_editor_variable_section_index");
    case "section_index_unavailable":
      return t("flow_step_editor_read_section_index_unavailable");
    case "fields_of_text":
      return t("flow_step_editor_read_fields_of_text", { step: step(meaning.order) });
    case "step_answer":
      return t("flows_chat_reference_value", {
        step: step(meaning.order),
        what: t("flows_chat_reference_value_text")
      });
    case "step_structured":
      return t("flows_chat_reference_value", {
        step: step(meaning.order),
        what: t("flows_chat_reference_value_structured")
      });
    case "step_field":
      return t("flows_chat_reference_value", { step: step(meaning.order), what: meaning.field });
    case "missing":
      return t("flow_editor_tools_preview_read_missing", { order: meaning.order });
    case "other":
      return token;
  }
}

/** What to change about a reference that reads nothing useful where it stands, or null. */
export function readWarning(
  meaning: ReadMeaning,
  flow: Pick<FlowPublic, "steps">,
  t: T
): string | null {
  switch (meaning.kind) {
    case "fields_of_text":
      return t("flow_step_editor_reference_warning_fields_of_text", {
        step: stepLabel(
          meaning.order,
          flow.steps.find((item) => item.step_order === meaning.order)?.user_description,
          t
        )
      });
    case "section_index_unavailable":
      return t("flow_step_editor_reference_warning_section_index");
    default:
      return null;
  }
}

/** What one reference a step can insert is, as the reference menus name it. */
export function variableEntryLabel(entry: VariableEntry, t: T): string {
  switch (entry.kind.type) {
    case "field":
      return entry.kind.label;
    case "upload":
      return t("flow_step_editor_variable_upload");
    case "transcription":
      return t("flow_step_editor_variable_transcription");
    case "date":
      return t("flow_step_editor_variable_date");
    case "section_index":
      return t("flow_step_editor_variable_section_index");
    case "previous_step":
      return t("flow_step_editor_variable_previous_step");
    case "step_text":
      return t("flow_step_editor_variable_step_text");
    case "step_structured":
      return t("flow_step_editor_variable_step_structured");
    case "step_field":
      return t("flow_step_editor_variable_step_field", { field: entry.kind.field });
  }
}

/** The heading a group of insertable references has in the reference menus. */
export function variableGroupTitle(group: VariableGroup, t: T): string {
  if (group.type === "fields") return t("flow_step_editor_variables_fields");
  if (group.type === "run") return t("flow_step_editor_variables_run");
  return stepLabel(group.stepOrder, group.stepName, t);
}
