import { m } from "$lib/paraglide/messages";

const CODE_TO_MESSAGE: Record<string, () => string> = {
  typed_io_duplicate_step_order: () => m.flow_validation_msg_duplicate_step_order(),
  typed_io_non_contiguous_step_order: () => m.flow_validation_msg_non_contiguous_step_order(),
  typed_io_multiple_flow_input_steps: () => m.flow_validation_msg_multiple_flow_input_steps(),
  typed_io_flow_input_position_invalid: () => m.flow_validation_msg_flow_input_position_invalid(),
  typed_io_invalid_input_source_position: () =>
    m.flow_validation_msg_invalid_input_source_position(),
  typed_io_unsupported_type: () => m.flow_validation_msg_unsupported_type(),
  typed_io_document_source_unsupported: () => m.flow_validation_msg_document_source_unsupported(),
  typed_io_audio_source_unsupported: () => m.flow_validation_msg_audio_source_unsupported(),
  typed_io_file_source_unsupported: () => m.flow_validation_msg_file_source_unsupported(),
  typed_io_invalid_input_source_combination: () =>
    m.flow_validation_msg_invalid_input_source_combination(),
  typed_io_missing_previous_step: () => m.flow_validation_msg_missing_previous_step(),
  typed_io_incompatible_type_chain: () => m.flow_validation_msg_incompatible_type_chain(),
  template_fill_no_template: () => m.flow_validation_msg_template_fill_no_template(),
  output_mode_incompatible: () => m.flow_validation_msg_output_mode_incompatible(),
  "deleted-step-reference": () => m.flow_validation_msg_deleted_step_reference(),
  assistant_save_failed: () => m.flow_validation_msg_assistant_save_failed(),
  // Server-side step-graph issue codes (FlowGraphIssueCode) that authoring
  // can trigger; the raw technical sentence stays available as detail.
  flow_http_post_output_must_be_terminal: () => m.flow_validation_msg_http_post_not_terminal(),
  flow_input_binding_unsupported_key: () => m.flow_validation_msg_input_binding_unsupported_key(),
  flow_input_binding_runtime_input_unused: () =>
    m.flow_validation_msg_input_binding_runtime_input_unused(),
  flow_step_invalid: () => m.flow_validation_msg_flow_step_invalid(),
  flow_input_contract_inapplicable: () => m.flow_validation_msg_input_contract_inapplicable(),
  invalid_input_contract_schema: () => m.flow_validation_msg_invalid_input_contract_schema(),
  invalid_output_contract_schema: () => m.flow_validation_msg_invalid_output_contract_schema(),
  output_contract_type_mismatch: () => m.flow_validation_msg_output_contract_type_mismatch(),
  flow_input_binding_future_step_reference: () => m.flow_validation_msg_input_binding_future_step(),
  flow_input_binding_invalid_step_reference: () =>
    m.flow_validation_msg_input_binding_invalid_step(),
  flow_input_binding_unknown_step_order: () => m.flow_validation_msg_input_binding_unknown_step(),
  duplicate_step_name: () => m.flow_validation_msg_duplicate_step_name(),
  citation_mode_unsupported: () => m.flow_validation_msg_citation_mode_unsupported(),
  template_fill_requires_docx: () => m.flow_validation_msg_template_fill_requires_docx(),
  output_contract_template_fill_incompatible: () =>
    m.flow_validation_msg_output_contract_template_fill_incompatible(),
  flow_review_policy_invalid: () => m.flow_validation_msg_review_policy_invalid(),
  flow_review_policy_outbound_output_unsupported: () =>
    m.flow_validation_msg_review_policy_outbound_unsupported(),
  transcribe_only_violation: () => m.flow_validation_msg_transcribe_only_violation(),
  flow_audio_transcription_required: () => m.flow_validation_msg_audio_transcription_required(),
  flow_audio_transcription_model_required: () =>
    m.flow_validation_msg_audio_transcription_model_required()
};

export function getValidationIssueMessage(code: string): string {
  return CODE_TO_MESSAGE[code]?.() ?? code;
}

export type ParsedValidationError =
  | { kind: "step"; code: string; stepOrder: number; detail?: string }
  | { kind: "assistant"; assistantId: string; message: string }
  | { kind: "flow"; code: string; message: string; detail?: string };

/**
 * Structured identity of a server-side validation failure, read from the
 * error payload the backend now emits (context.issue_code + step_order).
 */
export function parseServerValidationIdentity(error: {
  response?: unknown;
}): { code: string; stepOrder: number | null } | null {
  // The backend's GeneralError body arrives as EneoError.response;
  // context.issue_code is the one validation discriminator — a symbolic
  // top-level code alone is NOT treated as validation, so unrelated domain
  // errors are never misrouted into the banner.
  const response =
    typeof error.response === "object" && error.response !== null
      ? (error.response as Record<string, unknown>)
      : null;
  if (!response) return null;
  const context =
    typeof response.context === "object" && response.context !== null
      ? (response.context as Record<string, unknown>)
      : null;
  if (!context) return null;
  const code =
    typeof context.issue_code === "string" && context.issue_code ? context.issue_code : null;
  if (!code) return null;
  const stepOrder = typeof context.step_order === "number" ? context.step_order : null;
  return { code, stepOrder };
}

/**
 * Prefixes that encode `{code}:{stepOrder}` after the prefix.
 * Both typed-io and step-config errors are step-scoped.
 */
const STEP_SCOPED_PREFIXES = ["flow:typed-io:", "flow:step-config:", "flow:server:"] as const;
const ASSISTANT_PREFIX = "assistant:";
const FLOW_PREFIX = "flow:";

/**
 * Parse a validation error map entry into a structured object.
 *
 * Key formats:
 *   - `flow:typed-io:{code}:{stepOrder}`
 *   - `flow:step-config:{code}:{stepOrder}`
 *   - `assistant:{assistantId}`
 *   - `flow:{code}`
 */
export function parseValidationError(key: string, values: string[]): ParsedValidationError | null {
  for (const prefix of STEP_SCOPED_PREFIXES) {
    if (key.startsWith(prefix)) {
      const rest = key.slice(prefix.length);
      const lastColon = rest.lastIndexOf(":");
      const stepOrder = lastColon === -1 ? NaN : parseInt(rest.slice(lastColon + 1), 10);
      if (isNaN(stepOrder)) {
        // A flow-scoped server rejection has no step suffix; it still
        // belongs to the banner with the translated (or raw) message.
        if (prefix === "flow:server:") {
          return { kind: "flow", code: rest, message: values[0] ?? rest, detail: values[0] };
        }
        return null;
      }
      return { kind: "step", code: rest.slice(0, lastColon), stepOrder, detail: values[0] };
    }
  }

  if (key.startsWith(ASSISTANT_PREFIX)) {
    const assistantId = key.slice(ASSISTANT_PREFIX.length);
    return { kind: "assistant", assistantId, message: values[0] ?? key };
  }

  if (key.startsWith(FLOW_PREFIX)) {
    const code = key.slice(FLOW_PREFIX.length);
    return { kind: "flow", code, message: values[0] ?? key, detail: values[0] };
  }

  return null;
}
