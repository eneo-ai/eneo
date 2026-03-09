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
  "deleted-step-reference": () => m.flow_validation_msg_deleted_step_reference(),
  assistant_save_failed: () => m.flow_validation_msg_assistant_save_failed()
};

export function getValidationIssueMessage(code: string): string {
  return CODE_TO_MESSAGE[code]?.() ?? code;
}

export type ParsedValidationError =
  | { kind: "step"; code: string; stepOrder: number }
  | { kind: "assistant"; assistantId: string; message: string }
  | { kind: "flow"; code: string; message: string };

/**
 * Prefixes that encode `{code}:{stepOrder}` after the prefix.
 * Both typed-io and step-config errors are step-scoped.
 */
const STEP_SCOPED_PREFIXES = ["flow:typed-io:", "flow:step-config:"] as const;
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
export function parseValidationError(
  key: string,
  values: string[]
): ParsedValidationError | null {
  for (const prefix of STEP_SCOPED_PREFIXES) {
    if (key.startsWith(prefix)) {
      const rest = key.slice(prefix.length);
      const lastColon = rest.lastIndexOf(":");
      if (lastColon === -1) return null;
      const code = rest.slice(0, lastColon);
      const stepOrder = parseInt(rest.slice(lastColon + 1), 10);
      if (isNaN(stepOrder)) return null;
      return { kind: "step", code, stepOrder };
    }
  }

  if (key.startsWith(ASSISTANT_PREFIX)) {
    const assistantId = key.slice(ASSISTANT_PREFIX.length);
    return { kind: "assistant", assistantId, message: values[0] ?? key };
  }

  if (key.startsWith(FLOW_PREFIX)) {
    const code = key.slice(FLOW_PREFIX.length);
    return { kind: "flow", code, message: values[0] ?? key };
  }

  return null;
}
