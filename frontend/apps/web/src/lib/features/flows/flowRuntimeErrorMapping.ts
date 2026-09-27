import {
  FLOW_API_ERROR_CODE,
  FLOW_API_ERROR_CODES,
  EneoError,
  type FlowApiErrorCode
} from "@eneo/eneo-js";
import type { FlowRunError as FlowRunErrorContract } from "@eneo/eneo-js";
import { m } from "$lib/paraglide/messages";

export { FLOW_API_ERROR_CODE, FLOW_API_ERROR_CODES };
export type { FlowApiErrorCode };
export type FlowApiErrorMessageKey = `flow_error_${FlowApiErrorCode}`;

export type FlowApiErrorContext = {
  step_ids?: string[];
  checkpoint_id?: string;
  step_id?: string;
  step_order?: number;
  payload_field?: string;
  state?: string;
  expires_at?: string;
  expired_at?: string;
  /** Which boundary an oversized evidence export exceeded. */
  limit?: string;
  /** Why a limit refused, when the code alone is ambiguous (e.g. extraction_capacity). */
  reason?: string;
  /** Server-provided recovery guidance for the exceeded limit. */
  hint?: string;
};

export type FlowApiErrorDescriptor = {
  code: FlowApiErrorCode;
  messageKey: FlowApiErrorMessageKey;
  context: FlowApiErrorContext;
};

export type FlowReviewPolicyErrorStep = {
  step_order: number;
  user_description?: string | null;
  review_policy?: unknown | null;
};

export type FlowReviewPolicyAffectedStep = {
  step_order: number;
  user_description: string | null;
};

export type FlowRunError = FlowRunErrorContract;

const FLOW_API_ERROR_CODE_SET = new Set<FlowApiErrorCode>(FLOW_API_ERROR_CODES);

// One message per code, named literally so a missing code is a type error and
// the catalogue's unused-key check sees every message in use.
const FLOW_API_ERROR_MESSAGES = {
  flow_not_published: m.flow_error_flow_not_published,
  flow_review_history_too_large: m.flow_error_flow_review_history_too_large,
  flow_deleted: m.flow_error_flow_deleted,
  flow_owner_required: m.flow_error_flow_owner_required,
  flow_managed_assistant: m.flow_error_flow_managed_assistant,
  flow_service_key_admin_required: m.flow_error_flow_service_key_admin_required,
  flow_service_key_principal_not_supported: m.flow_error_flow_service_key_principal_not_supported,
  flow_service_key_space_id_required: m.flow_error_flow_service_key_space_id_required,
  flow_run_invalid_idempotency_key: m.flow_error_flow_run_invalid_idempotency_key,
  flow_run_stale_version: m.flow_error_flow_run_stale_version,
  flow_run_retry_source_not_failed: m.flow_error_flow_run_retry_source_not_failed,
  flow_run_retry_source_version_stale: m.flow_error_flow_run_retry_source_version_stale,
  flow_run_retry_nothing_to_reuse: m.flow_error_flow_run_retry_nothing_to_reuse,
  flow_run_retry_prefix_unsupported: m.flow_error_flow_run_retry_prefix_unsupported,
  flow_run_required_step_input_missing: m.flow_error_flow_run_required_step_input_missing,
  flow_run_runtime_input_disabled: m.flow_error_flow_run_runtime_input_disabled,
  flow_run_top_level_file_ids_not_supported: m.flow_error_flow_run_top_level_file_ids_not_supported,
  flow_run_idempotency_conflict: m.flow_error_flow_run_idempotency_conflict,
  flow_run_concurrency_limit_reached: m.flow_error_flow_run_concurrency_limit_reached,
  flow_run_redispatch_conflict: m.flow_error_flow_run_redispatch_conflict,
  flow_run_redispatch_audit_unavailable: m.flow_error_flow_run_redispatch_audit_unavailable,
  flow_run_invalid_step_inputs: m.flow_error_flow_run_invalid_step_inputs,
  flow_run_unknown_step_input: m.flow_error_flow_run_unknown_step_input,
  flow_run_step_input_max_files_exceeded: m.flow_error_flow_run_step_input_max_files_exceeded,
  flow_run_file_not_accessible: m.flow_error_flow_run_file_not_accessible,
  flow_run_file_not_bound_to_flow: m.flow_error_flow_run_file_not_bound_to_flow,
  flow_run_file_access_audit_unavailable: m.flow_error_flow_run_file_access_audit_unavailable,
  flow_run_step_input_file_too_large: m.flow_error_flow_run_step_input_file_too_large,
  flow_run_upload_pdf_exceeds_limit: m.flow_error_flow_run_upload_pdf_exceeds_limit,
  flow_run_audio_exceeds_limit: m.flow_error_flow_run_audio_exceeds_limit,
  flow_run_audio_unreadable: m.flow_error_flow_run_audio_unreadable,
  flow_run_audio_length_unknown: m.flow_error_flow_run_audio_length_unknown,
  flow_run_audio_measurement_busy: m.flow_error_flow_run_audio_measurement_busy,
  flow_run_step_input_mimetype_rejected: m.flow_error_flow_run_step_input_mimetype_rejected,
  flow_run_aggregate_max_files_exceeded: m.flow_error_flow_run_aggregate_max_files_exceeded,
  flow_run_reserved_input_payload_key: m.flow_error_flow_run_reserved_input_payload_key,
  flow_run_speaker_labels_not_selectable: m.flow_error_flow_run_speaker_labels_not_selectable,
  flow_run_max_speakers_not_available: m.flow_error_flow_run_max_speakers_not_available,
  flow_run_input_payload_too_large: m.flow_error_flow_run_input_payload_too_large,
  flow_run_input_exceeds_limit: m.flow_error_flow_run_input_exceeds_limit,
  flow_input_required_field_missing: m.flow_error_flow_input_required_field_missing,
  flow_input_required_field_empty: m.flow_error_flow_input_required_field_empty,
  flow_input_type_mismatch: m.flow_error_flow_input_type_mismatch,
  flow_input_invalid_number: m.flow_error_flow_input_invalid_number,
  flow_input_invalid_date: m.flow_error_flow_input_invalid_date,
  flow_input_invalid_option: m.flow_error_flow_input_invalid_option,
  flow_input_invalid_multiselect_value: m.flow_error_flow_input_invalid_multiselect_value,
  flow_input_invalid_multiselect_type: m.flow_error_flow_input_invalid_multiselect_type,
  flow_input_invalid_list_value: m.flow_error_flow_input_invalid_list_value,
  flow_input_invalid_list_type: m.flow_error_flow_input_invalid_list_type,
  flow_run_access_denied: m.flow_error_flow_run_access_denied,
  flow_run_cancelled: m.flow_error_flow_run_cancelled,
  flow_run_user_cancelled: m.flow_error_flow_run_user_cancelled,
  flow_dispatch_failed: m.flow_error_flow_dispatch_failed,
  flow_missing_principal: m.flow_error_flow_missing_principal,
  flow_service_principal_disabled: m.flow_error_flow_service_principal_disabled,
  flow_runtime_actor_invalid: m.flow_error_flow_runtime_actor_invalid,
  flow_task_timeout: m.flow_error_flow_task_timeout,
  flow_task_failure: m.flow_error_flow_task_failure,
  flow_worker_stalled: m.flow_error_flow_worker_stalled,
  flow_run_abandoned: m.flow_error_flow_run_abandoned,
  flow_run_error_payload_invalid: m.flow_error_flow_run_error_payload_invalid,
  flow_run_evidence_forbidden: m.flow_error_flow_run_evidence_forbidden,
  flow_run_evidence_raw_export_forbidden: m.flow_error_flow_run_evidence_raw_export_forbidden,
  flow_run_artifact_not_found: m.flow_error_flow_run_artifact_not_found,
  flow_run_artifact_content_unavailable: m.flow_error_flow_run_artifact_content_unavailable,
  flow_run_input_file_not_found: m.flow_error_flow_run_input_file_not_found,
  flow_run_input_file_content_unavailable: m.flow_error_flow_run_input_file_content_unavailable,
  flow_audit_outbox_delivery_not_found: m.flow_error_flow_audit_outbox_delivery_not_found,
  flow_audit_outbox_redrive_conflict: m.flow_error_flow_audit_outbox_redrive_conflict,
  flow_definition_checksum_mismatch: m.flow_error_flow_definition_checksum_mismatch,
  flow_definition_invalid: m.flow_error_flow_definition_invalid,
  flow_definition_schema_version_missing: m.flow_error_flow_definition_schema_version_missing,
  flow_definition_schema_version_unsupported:
    m.flow_error_flow_definition_schema_version_unsupported,
  flow_definition_flow_id_invalid: m.flow_error_flow_definition_flow_id_invalid,
  flow_definition_steps_invalid: m.flow_error_flow_definition_steps_invalid,
  flow_definition_no_executable_steps: m.flow_error_flow_definition_no_executable_steps,
  flow_assistant_model_provider_required: m.flow_error_flow_assistant_model_provider_required,
  flow_assistant_snapshot_republish_required:
    m.flow_error_flow_assistant_snapshot_republish_required,
  flow_assistant_snapshot_drift: m.flow_error_flow_assistant_snapshot_drift,
  flow_input_contract_inapplicable: m.flow_error_flow_input_contract_inapplicable,
  flow_step_missing: m.flow_error_flow_step_missing,
  flow_step_attempt_start_failed: m.flow_error_flow_step_attempt_start_failed,
  flow_step_execution_failed: m.flow_error_flow_step_execution_failed,
  flow_provider_rate_limited: m.flow_error_flow_provider_rate_limited,
  flow_provider_unavailable: m.flow_error_flow_provider_unavailable,
  flow_provider_call_evidence_persistence_failed:
    m.flow_error_flow_provider_call_evidence_persistence_failed,
  flow_webhook_delivery_failed: m.flow_error_flow_webhook_delivery_failed,
  flow_runtime_file_empty: m.flow_error_flow_runtime_file_empty,
  flow_runtime_file_attached: m.flow_error_flow_runtime_file_attached,
  flow_live_transcription_unavailable: m.flow_error_flow_live_transcription_unavailable,
  flow_run_live_transcript_requires_one_audio_file:
    m.flow_error_flow_run_live_transcript_requires_one_audio_file,
  flow_run_live_transcript_not_found: m.flow_error_flow_run_live_transcript_not_found,
  flow_run_single_recording_requires_audio_step:
    m.flow_error_flow_run_single_recording_requires_audio_step,
  flow_run_live_transcript_already_bound: m.flow_error_flow_run_live_transcript_already_bound,
  flow_evidence_audit_logging_failed: m.flow_error_flow_evidence_audit_logging_failed,
  flow_evidence_export_reason_required: m.flow_error_flow_evidence_export_reason_required,
  flow_evidence_export_too_large: m.flow_error_flow_evidence_export_too_large,
  flow_model_capacity_undeclared: m.flow_error_flow_model_capacity_undeclared,
  flow_llm_output_truncated: m.flow_error_flow_llm_output_truncated,
  flow_llm_output_whitespace_abort: m.flow_error_flow_llm_output_whitespace_abort,
  flow_llm_request_timeout: m.flow_error_flow_llm_request_timeout,
  flow_step_timeout: m.flow_error_flow_step_timeout,
  flow_runtime_input_not_consumed: m.flow_error_flow_runtime_input_not_consumed,
  flow_mapped_provider_call_limit_exceeded: m.flow_error_flow_mapped_provider_call_limit_exceeded,
  flow_summarization_non_convergent: m.flow_error_flow_summarization_non_convergent,
  flow_unsupported_output_mode: m.flow_error_flow_unsupported_output_mode,
  flow_unsupported_output_type: m.flow_error_flow_unsupported_output_type,
  typed_io_contract_violation: m.flow_error_typed_io_contract_violation,
  typed_io_validation_failed: m.flow_error_typed_io_validation_failed,
  typed_io_variable_resolution_failed: m.flow_error_typed_io_variable_resolution_failed,
  typed_io_audio_invalid_file_type: m.flow_error_typed_io_audio_invalid_file_type,
  typed_io_audio_missing_file: m.flow_error_typed_io_audio_missing_file,
  typed_io_audio_source_unsupported: m.flow_error_typed_io_audio_source_unsupported,
  typed_io_audio_too_many_files: m.flow_error_typed_io_audio_too_many_files,
  typed_io_audio_exceeds_limit: m.flow_error_typed_io_audio_exceeds_limit,
  typed_io_document_source_unsupported: m.flow_error_typed_io_document_source_unsupported,
  typed_io_empty_extraction: m.flow_error_typed_io_empty_extraction,
  typed_io_file_not_found: m.flow_error_typed_io_file_not_found,
  typed_io_file_source_unsupported: m.flow_error_typed_io_file_source_unsupported,
  typed_io_http_connection_error: m.flow_error_typed_io_http_connection_error,
  typed_io_http_invalid_config: m.flow_error_typed_io_http_invalid_config,
  typed_io_http_invalid_url: m.flow_error_typed_io_http_invalid_url,
  typed_io_http_malformed_response: m.flow_error_typed_io_http_malformed_response,
  typed_io_http_non_success: m.flow_error_typed_io_http_non_success,
  typed_io_http_response_too_large: m.flow_error_typed_io_http_response_too_large,
  typed_io_http_ssrf_blocked: m.flow_error_typed_io_http_ssrf_blocked,
  typed_io_http_timeout: m.flow_error_typed_io_http_timeout,
  typed_io_input_exceeds_model_window: m.flow_error_typed_io_input_exceeds_model_window,
  typed_io_input_too_large: m.flow_error_typed_io_input_too_large,
  typed_io_structured_output_exceeds_limit: m.flow_error_typed_io_structured_output_exceeds_limit,
  typed_io_invalid_file_type: m.flow_error_typed_io_invalid_file_type,
  typed_io_invalid_input_source_combination: m.flow_error_typed_io_invalid_input_source_combination,
  typed_io_invalid_input_source_position: m.flow_error_typed_io_invalid_input_source_position,
  typed_io_invalid_json_input: m.flow_error_typed_io_invalid_json_input,
  typed_io_invalid_output_mode_combination: m.flow_error_typed_io_invalid_output_mode_combination,
  typed_io_invalid_schema: m.flow_error_typed_io_invalid_schema,
  typed_io_missing_required_files: m.flow_error_typed_io_missing_required_files,
  typed_io_output_parse_failed: m.flow_error_typed_io_output_parse_failed,
  typed_io_render_failed: m.flow_error_typed_io_render_failed,
  typed_io_template_checksum_mismatch: m.flow_error_typed_io_template_checksum_mismatch,
  typed_io_template_render_failed: m.flow_error_typed_io_template_render_failed,
  typed_io_transcript_too_large: m.flow_error_typed_io_transcript_too_large,
  typed_io_transcription_config_invalid: m.flow_error_typed_io_transcription_config_invalid,
  typed_io_transcription_empty: m.flow_error_typed_io_transcription_empty,
  typed_io_transcription_failed: m.flow_error_typed_io_transcription_failed,
  typed_io_transcription_model_missing: m.flow_error_typed_io_transcription_model_missing,
  typed_io_transcription_model_unavailable: m.flow_error_typed_io_transcription_model_unavailable,
  typed_io_transcription_not_enabled: m.flow_error_typed_io_transcription_not_enabled,
  typed_io_unsupported_type: m.flow_error_typed_io_unsupported_type,
  flow_published_form_schema_invalid: m.flow_error_flow_published_form_schema_invalid,
  flow_review_policy_invalid: m.flow_error_flow_review_policy_invalid,
  flow_review_stale_revision: m.flow_error_flow_review_stale_revision,
  flow_review_expired: m.flow_error_flow_review_expired,
  flow_review_not_active: m.flow_error_flow_review_not_active,
  flow_review_step_result_not_found: m.flow_error_flow_review_step_result_not_found,
  flow_review_edit_not_allowed: m.flow_error_flow_review_edit_not_allowed,
  flow_review_edit_file_backed_unsupported: m.flow_error_flow_review_edit_file_backed_unsupported,
  flow_review_edit_output_too_large: m.flow_error_flow_review_edit_output_too_large,
  flow_review_checkpoint_not_found: m.flow_error_flow_review_checkpoint_not_found,
  flow_review_reject_reason_required: m.flow_error_flow_review_reject_reason_required,
  flow_review_reject_reason_too_long: m.flow_error_flow_review_reject_reason_too_long,
  flow_review_idempotency_key_required: m.flow_error_flow_review_idempotency_key_required,
  flow_review_not_approved: m.flow_error_flow_review_not_approved,
  flow_review_already_resumed: m.flow_error_flow_review_already_resumed,
  flow_review_rejected: m.flow_error_flow_review_rejected,
  flow_review_cancelled: m.flow_error_flow_review_cancelled,
  flow_transcript_corrections_stale_revision:
    m.flow_error_flow_transcript_corrections_stale_revision,
  flow_transcript_corrections_segments_unavailable:
    m.flow_error_flow_transcript_corrections_segments_unavailable,
  flow_transcript_corrections_invalid_occurrence:
    m.flow_error_flow_transcript_corrections_invalid_occurrence,
  flow_transcript_corrections_invalid_speaker_edit:
    m.flow_error_flow_transcript_corrections_invalid_speaker_edit,
  flow_review_open_active_conflict_invariant:
    m.flow_error_flow_review_open_active_conflict_invariant,
  flow_review_open_step_result_incomplete_invariant:
    m.flow_error_flow_review_open_step_result_incomplete_invariant,
  flow_review_open_multiple_active_checkpoints_invariant:
    m.flow_error_flow_review_open_multiple_active_checkpoints_invariant,
  flow_template_invalid_archive: m.flow_error_flow_template_invalid_archive,
  flow_template_no_controls: m.flow_error_flow_template_no_controls,
  flow_template_control_untagged: m.flow_error_flow_template_control_untagged,
  flow_template_control_placement: m.flow_error_flow_template_control_placement,
  flow_template_control_nested: m.flow_error_flow_template_control_nested,
  flow_template_control_mapped: m.flow_error_flow_template_control_mapped,
  flow_template_control_unsupported: m.flow_error_flow_template_control_unsupported,
  flow_template_control_duplicate: m.flow_error_flow_template_control_duplicate,
  flow_template_corrupted_archive: m.flow_error_flow_template_corrupted_archive,
  flow_template_macro_not_allowed: m.flow_error_flow_template_macro_not_allowed,
  flow_template_missing_required_parts: m.flow_error_flow_template_missing_required_parts,
  flow_template_not_accessible: m.flow_error_flow_template_not_accessible,
  flow_template_read_only: m.flow_error_flow_template_read_only,
  flow_template_unsupported_extension: m.flow_error_flow_template_unsupported_extension,
  flow_template_missing_content: m.flow_error_flow_template_missing_content,
  flow_template_in_use: m.flow_error_flow_template_in_use,
  flow_template_download_audit_unavailable: m.flow_error_flow_template_download_audit_unavailable,
  flow_package_export_audit_unavailable: m.flow_error_flow_package_export_audit_unavailable,
  flow_assistant_snapshot_resource_invalid: m.flow_error_flow_assistant_snapshot_resource_invalid
} satisfies Record<FlowApiErrorCode, () => string>;

const UPLOAD_ERROR_HINTS: Record<string, string> = {
  timeout: " Försök igen med en mindre fil eller kontrollera din internetanslutning.",
  file_too_large: " Välj en mindre fil.",
  network: " Kontrollera din internetanslutning och försök igen."
};

export function classifyUploadError(
  message: string
): "timeout" | "file_too_large" | "network" | "unknown" {
  const lower = message.toLowerCase();
  if (
    lower.includes("timeout") ||
    lower.includes("timed out") ||
    lower.includes("did not start") ||
    lower.includes("stalled") ||
    lower.includes("server did not respond")
  )
    return "timeout";
  if (lower.includes("too large") || lower.includes("max") || lower.includes("storlek"))
    return "file_too_large";
  if (lower.includes("network") || lower.includes("fetch") || lower.includes("nät"))
    return "network";
  return "unknown";
}

export function getUploadErrorHint(errorKind: ReturnType<typeof classifyUploadError>): string {
  return UPLOAD_ERROR_HINTS[errorKind] ?? "";
}

const MISSING_TEMPLATE_CONTENT_PATTERNS = [
  "selected template file has no binary content",
  "published docx template file has no binary content",
  "file content is missing"
];

function isObject(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function readOptionalStringArray(value: unknown): string[] | undefined {
  if (!Array.isArray(value)) return undefined;
  const strings = value.filter((item): item is string => typeof item === "string");
  return strings.length > 0 ? strings : undefined;
}

function readOptionalString(value: unknown): string | undefined {
  return typeof value === "string" ? value : undefined;
}

function readOptionalNumber(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function extractFlowApiErrorContext(value: unknown): FlowApiErrorContext {
  if (!isObject(value)) return {};

  const context: FlowApiErrorContext = {};
  const stepIds = readOptionalStringArray(value.step_ids);
  if (stepIds) context.step_ids = stepIds;

  const checkpointId = readOptionalString(value.checkpoint_id);
  if (checkpointId) context.checkpoint_id = checkpointId;

  const limit = readOptionalString(value.limit);
  if (limit) context.limit = limit;

  const reason = readOptionalString(value.reason);
  if (reason) context.reason = reason;

  const hint = readOptionalString(value.hint);
  if (hint) context.hint = hint;

  const stepId = readOptionalString(value.step_id);
  if (stepId) context.step_id = stepId;

  const stepOrder = readOptionalNumber(value.step_order);
  if (stepOrder !== undefined) context.step_order = stepOrder;

  const payloadField = readOptionalString(value.payload_field);
  if (payloadField) context.payload_field = payloadField;

  const state = readOptionalString(value.state);
  if (state) context.state = state;

  const expiresAt = readOptionalString(value.expires_at);
  if (expiresAt) context.expires_at = expiresAt;

  const expiredAt = readOptionalString(value.expired_at);
  if (expiredAt) context.expired_at = expiredAt;

  return context;
}

function isFlowApiErrorCode(code: string): code is FlowApiErrorCode {
  return FLOW_API_ERROR_CODE_SET.has(code as FlowApiErrorCode);
}

function getResponseCode(error: EneoError): string | null {
  if (isObject(error.response) && typeof error.response.code === "string") {
    return error.response.code;
  }
  return typeof error.code === "string" ? error.code : null;
}

function responseContext(error: EneoError): FlowApiErrorContext {
  if (!isObject(error.response)) return {};
  return extractFlowApiErrorContext(error.response.context);
}

function messageKeyForCode(code: FlowApiErrorCode): FlowApiErrorMessageKey {
  return `flow_error_${code}`;
}

export function isReviewPolicyInvalidRunError(error: FlowRunError | null | undefined): boolean {
  return error?.code === FLOW_API_ERROR_CODE.REVIEW_POLICY_INVALID;
}

export function reviewPolicyRunErrorStepOrder(
  error: FlowRunError | null | undefined
): number | null {
  const stepOrder = error?.step_order;
  return typeof stepOrder === "number" && Number.isFinite(stepOrder) ? stepOrder : null;
}

export function getReviewPolicyAffectedStepsFromRunError(
  error: FlowRunError | null | undefined,
  steps: readonly FlowReviewPolicyErrorStep[]
): FlowReviewPolicyAffectedStep[] {
  if (!isReviewPolicyInvalidRunError(error)) return [];

  const stepOrder = reviewPolicyRunErrorStepOrder(error);
  if (stepOrder !== null) {
    const step = steps.find((candidate) => candidate.step_order === stepOrder);
    return [
      {
        step_order: stepOrder,
        user_description: step?.user_description?.trim() || null
      }
    ];
  }

  return steps
    .filter((step) => step.review_policy != null)
    .map((step) => ({
      step_order: step.step_order,
      user_description: step.user_description?.trim() || null
    }));
}

export function isReviewPolicyRunErrorStepExact(error: FlowRunError | null | undefined): boolean {
  return reviewPolicyRunErrorStepOrder(error) !== null;
}

export function isReviewPolicyRunErrorRelevantForStep(
  error: FlowRunError | null | undefined,
  stepOrder: number,
  reviewPolicy: unknown | null | undefined
): boolean {
  if (!isReviewPolicyInvalidRunError(error)) return true;

  const affectedStepOrder = reviewPolicyRunErrorStepOrder(error);
  if (affectedStepOrder !== null) return affectedStepOrder === stepOrder;

  return reviewPolicy != null;
}

export function getReviewPolicyErrorStepsFromDefinitionSnapshot(
  steps: readonly unknown[]
): FlowReviewPolicyErrorStep[] {
  return steps.flatMap((step): FlowReviewPolicyErrorStep[] => {
    if (!isObject(step)) return [];

    const stepOrder = readOptionalNumber(step.step_order);
    if (stepOrder === undefined) return [];

    return [
      {
        step_order: stepOrder,
        user_description: readOptionalString(step.user_description) ?? null,
        review_policy: step.review_policy ?? null
      }
    ];
  });
}

export function extractFlowApiError(error: unknown): {
  code: FlowApiErrorCode;
  context: FlowApiErrorContext;
} | null {
  if (!(error instanceof EneoError)) return null;

  const code = getResponseCode(error);
  if (!code || !isFlowApiErrorCode(code)) return null;

  return {
    code,
    context: responseContext(error)
  };
}

export function describeFlowApiError(error: unknown): FlowApiErrorDescriptor | null {
  const parsed = extractFlowApiError(error);
  if (!parsed) return null;

  return {
    code: parsed.code,
    messageKey: messageKeyForCode(parsed.code),
    context: parsed.context
  };
}

function descriptorForCode(
  code: string | null | undefined,
  context: FlowApiErrorContext = {}
): FlowApiErrorDescriptor | null {
  if (!code || !isFlowApiErrorCode(code)) return null;
  return {
    code,
    messageKey: messageKeyForCode(code),
    context
  };
}

export function describeFlowRunError(error: unknown): FlowApiErrorDescriptor | null {
  if (!isObject(error)) return null;

  const context: FlowApiErrorContext = {};
  const stepId = readOptionalString(error.step_id);
  if (stepId) context.step_id = stepId;

  const stepOrder = readOptionalNumber(error.step_order);
  if (stepOrder !== undefined) {
    context.step_order = stepOrder;
  }

  return descriptorForCode(readOptionalString(error.code), context);
}

function resolveFlowApiErrorMessage(descriptor: FlowApiErrorDescriptor): string {
  // A PDF refused because the server's extraction capacity was busy is a
  // valid file: the guidance is to wait and retry, not to split it.
  if (
    descriptor.code === FLOW_API_ERROR_CODE.RUN_UPLOAD_PDF_EXCEEDS_LIMIT &&
    descriptor.context.reason === "extraction_capacity"
  ) {
    return m.flow_upload_pdf_extraction_busy();
  }
  return FLOW_API_ERROR_MESSAGES[descriptor.code]();
}

function matchesMissingTemplateContentError(readableMessage: string): boolean {
  const normalized = readableMessage.toLowerCase();
  return MISSING_TEMPLATE_CONTENT_PATTERNS.some((pattern) => normalized.includes(pattern));
}

export function getFlowRuntimeErrorMessage(error: unknown, fallbackMessage: string): string {
  if (!(error instanceof EneoError)) {
    return fallbackMessage;
  }

  const descriptor = describeFlowApiError(error);
  if (descriptor) return resolveFlowApiErrorMessage(descriptor);

  const readable = error.getReadableMessage();
  if (matchesMissingTemplateContentError(readable)) {
    return getFlowRuntimeErrorMessageByCode("flow_template_missing_content") ?? readable;
  }

  return readable;
}

export function getFlowRuntimeErrorMessageByCode(code: string | null | undefined): string | null {
  const descriptor = descriptorForCode(code);
  return descriptor ? resolveFlowApiErrorMessage(descriptor) : null;
}

export function getFlowRunErrorMessage(error: FlowRunError | null | undefined): string | null {
  const descriptor = describeFlowRunError(error);
  return descriptor ? resolveFlowApiErrorMessage(descriptor) : null;
}

const MIME_FRIENDLY_NAMES: Record<string, string> = {
  "application/pdf": "PDF",
  "application/msword": "Word",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "Word (.docx)",
  "application/vnd.ms-excel": "Excel",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "Excel (.xlsx)",
  "application/vnd.ms-powerpoint": "PowerPoint",
  "application/vnd.openxmlformats-officedocument.presentationml.presentation": "PowerPoint (.pptx)",
  "text/csv": "CSV",
  "application/csv": "CSV",
  "text/plain": "Text",
  "text/html": "HTML",
  "text/markdown": "Markdown",
  "application/json": "JSON",
  "application/xml": "XML",
  "image/png": "PNG",
  "image/jpeg": "JPEG",
  "image/gif": "GIF",
  "image/webp": "WebP",
  "image/svg+xml": "SVG",
  "audio/mpeg": "MP3",
  "audio/wav": "WAV",
  "audio/ogg": "OGG",
  "audio/webm": "WebM (ljud)",
  "audio/mp4": "M4A",
  "video/mp4": "MP4",
  "video/webm": "WebM",
  "audio/*": "Ljudfiler",
  "video/*": "Videofiler",
  "image/*": "Bildfiler"
};

export function friendlyMimeNames(mimetypes: string[]): string[] {
  const names = mimetypes.map((mime) => MIME_FRIENDLY_NAMES[mime] ?? mime);
  return [...new Set(names)];
}
