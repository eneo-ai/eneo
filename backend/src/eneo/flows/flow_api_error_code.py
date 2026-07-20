from __future__ import annotations

from enum import Enum, unique


@unique
class FlowApiErrorCode(str, Enum):
    """Public Flow error codes with generated SDK and localized client messages."""

    FLOW_NOT_PUBLISHED = "flow_not_published"
    FLOW_DELETED = "flow_deleted"
    OWNER_REQUIRED = "flow_owner_required"
    SERVICE_KEY_ADMIN_REQUIRED = "flow_service_key_admin_required"
    SERVICE_KEY_PRINCIPAL_NOT_SUPPORTED = "flow_service_key_principal_not_supported"
    RUN_INVALID_IDEMPOTENCY_KEY = "flow_run_invalid_idempotency_key"
    RUN_STALE_VERSION = "flow_run_stale_version"
    RUN_REQUIRED_STEP_INPUT_MISSING = "flow_run_required_step_input_missing"
    RUN_RUNTIME_INPUT_DISABLED = "flow_run_runtime_input_disabled"
    RUN_TOP_LEVEL_FILE_IDS_NOT_SUPPORTED = "flow_run_top_level_file_ids_not_supported"
    RUN_IDEMPOTENCY_CONFLICT = "flow_run_idempotency_conflict"
    RUN_CONCURRENCY_LIMIT_REACHED = "flow_run_concurrency_limit_reached"
    RUN_INVALID_STEP_INPUTS = "flow_run_invalid_step_inputs"
    RUN_UNKNOWN_STEP_INPUT = "flow_run_unknown_step_input"
    RUN_STEP_INPUT_MAX_FILES_EXCEEDED = "flow_run_step_input_max_files_exceeded"
    RUN_FILE_NOT_ACCESSIBLE = "flow_run_file_not_accessible"
    RUN_FILE_NOT_BOUND_TO_FLOW = "flow_run_file_not_bound_to_flow"
    RUN_STEP_INPUT_FILE_TOO_LARGE = "flow_run_step_input_file_too_large"
    RUN_STEP_INPUT_MIMETYPE_REJECTED = "flow_run_step_input_mimetype_rejected"
    RUN_AGGREGATE_MAX_FILES_EXCEEDED = "flow_run_aggregate_max_files_exceeded"
    RUN_RESERVED_INPUT_PAYLOAD_KEY = "flow_run_reserved_input_payload_key"
    RUN_INPUT_PAYLOAD_TOO_LARGE = "flow_run_input_payload_too_large"
    INPUT_REQUIRED_FIELD_MISSING = "flow_input_required_field_missing"
    INPUT_REQUIRED_FIELD_EMPTY = "flow_input_required_field_empty"
    INPUT_TYPE_MISMATCH = "flow_input_type_mismatch"
    INPUT_INVALID_NUMBER = "flow_input_invalid_number"
    INPUT_INVALID_DATE = "flow_input_invalid_date"
    INPUT_INVALID_OPTION = "flow_input_invalid_option"
    INPUT_INVALID_MULTISELECT_VALUE = "flow_input_invalid_multiselect_value"
    INPUT_INVALID_MULTISELECT_TYPE = "flow_input_invalid_multiselect_type"
    RUN_ACCESS_DENIED = "flow_run_access_denied"
    RUN_CANCELLED = "flow_run_cancelled"
    RUN_USER_CANCELLED = "flow_run_user_cancelled"
    RUN_DISPATCH_FAILED = "flow_dispatch_failed"
    RUN_MISSING_PRINCIPAL = "flow_missing_principal"
    RUN_SERVICE_PRINCIPAL_DISABLED = "flow_service_principal_disabled"
    RUN_RUNTIME_ACTOR_INVALID = "flow_runtime_actor_invalid"
    RUN_TASK_TIMEOUT = "flow_task_timeout"
    RUN_TASK_FAILURE = "flow_task_failure"
    RUN_WORKER_STALLED = "flow_worker_stalled"
    RUN_ERROR_PAYLOAD_INVALID = "flow_run_error_payload_invalid"
    RUN_EVIDENCE_FORBIDDEN = "flow_run_evidence_forbidden"
    RUN_EVIDENCE_RAW_EXPORT_FORBIDDEN = "flow_run_evidence_raw_export_forbidden"
    RUN_ARTIFACT_NOT_FOUND = "flow_run_artifact_not_found"
    RUN_ARTIFACT_CONTENT_UNAVAILABLE = "flow_run_artifact_content_unavailable"
    DEFINITION_CHECKSUM_MISMATCH = "flow_definition_checksum_mismatch"
    DEFINITION_INVALID = "flow_definition_invalid"
    DEFINITION_SCHEMA_VERSION_MISSING = "flow_definition_schema_version_missing"
    DEFINITION_SCHEMA_VERSION_UNSUPPORTED = "flow_definition_schema_version_unsupported"
    DEFINITION_FLOW_ID_INVALID = "flow_definition_flow_id_invalid"
    DEFINITION_STEPS_INVALID = "flow_definition_steps_invalid"
    DEFINITION_NO_EXECUTABLE_STEPS = "flow_definition_no_executable_steps"
    ASSISTANT_SNAPSHOT_DRIFT = "flow_assistant_snapshot_drift"
    INPUT_CONTRACT_INAPPLICABLE = "flow_input_contract_inapplicable"
    STEP_MISSING = "flow_step_missing"
    STEP_ATTEMPT_START_FAILED = "flow_step_attempt_start_failed"
    STEP_EXECUTION_FAILED = "flow_step_execution_failed"
    WEBHOOK_DELIVERY_FAILED = "flow_webhook_delivery_failed"
    RUNTIME_FILE_EMPTY = "flow_runtime_file_empty"
    RUNTIME_FILE_ATTACHED = "flow_runtime_file_attached"
    EVIDENCE_AUDIT_LOGGING_FAILED = "flow_evidence_audit_logging_failed"
    EVIDENCE_EXPORT_REASON_REQUIRED = "flow_evidence_export_reason_required"
    LLM_REQUEST_TIMEOUT = "flow_llm_request_timeout"
    RUNTIME_INPUT_NOT_CONSUMED = "flow_runtime_input_not_consumed"
    UNSUPPORTED_OUTPUT_MODE = "flow_unsupported_output_mode"
    UNSUPPORTED_OUTPUT_TYPE = "flow_unsupported_output_type"
    TYPED_IO_CONTRACT_VIOLATION = "typed_io_contract_violation"
    TYPED_IO_VALIDATION_FAILED = "typed_io_validation_failed"
    TYPED_IO_VARIABLE_RESOLUTION_FAILED = "typed_io_variable_resolution_failed"
    TYPED_IO_AUDIO_INVALID_FILE_TYPE = "typed_io_audio_invalid_file_type"
    TYPED_IO_AUDIO_MISSING_FILE = "typed_io_audio_missing_file"
    TYPED_IO_AUDIO_SOURCE_UNSUPPORTED = "typed_io_audio_source_unsupported"
    TYPED_IO_AUDIO_TOO_MANY_FILES = "typed_io_audio_too_many_files"
    TYPED_IO_DOCUMENT_SOURCE_UNSUPPORTED = "typed_io_document_source_unsupported"
    TYPED_IO_EMPTY_EXTRACTION = "typed_io_empty_extraction"
    TYPED_IO_FILE_NOT_FOUND = "typed_io_file_not_found"
    TYPED_IO_FILE_SOURCE_UNSUPPORTED = "typed_io_file_source_unsupported"
    TYPED_IO_HTTP_CONNECTION_ERROR = "typed_io_http_connection_error"
    TYPED_IO_HTTP_INVALID_CONFIG = "typed_io_http_invalid_config"
    TYPED_IO_HTTP_INVALID_URL = "typed_io_http_invalid_url"
    TYPED_IO_HTTP_MALFORMED_RESPONSE = "typed_io_http_malformed_response"
    TYPED_IO_HTTP_NON_SUCCESS = "typed_io_http_non_success"
    TYPED_IO_HTTP_RESPONSE_TOO_LARGE = "typed_io_http_response_too_large"
    TYPED_IO_HTTP_SSRF_BLOCKED = "typed_io_http_ssrf_blocked"
    TYPED_IO_HTTP_TIMEOUT = "typed_io_http_timeout"
    TYPED_IO_INPUT_EXCEEDS_MODEL_WINDOW = "typed_io_input_exceeds_model_window"
    TYPED_IO_INPUT_TOO_LARGE = "typed_io_input_too_large"
    TYPED_IO_INVALID_FILE_TYPE = "typed_io_invalid_file_type"
    TYPED_IO_INVALID_INPUT_SOURCE_COMBINATION = (
        "typed_io_invalid_input_source_combination"
    )
    TYPED_IO_INVALID_INPUT_SOURCE_POSITION = "typed_io_invalid_input_source_position"
    TYPED_IO_INVALID_JSON_INPUT = "typed_io_invalid_json_input"
    TYPED_IO_INVALID_OUTPUT_MODE_COMBINATION = (
        "typed_io_invalid_output_mode_combination"
    )
    TYPED_IO_INVALID_SCHEMA = "typed_io_invalid_schema"
    TYPED_IO_MISSING_REQUIRED_FILES = "typed_io_missing_required_files"
    TYPED_IO_OUTPUT_PARSE_FAILED = "typed_io_output_parse_failed"
    TYPED_IO_RENDER_FAILED = "typed_io_render_failed"
    TYPED_IO_TEMPLATE_CHECKSUM_MISMATCH = "typed_io_template_checksum_mismatch"
    TYPED_IO_TEMPLATE_RENDER_FAILED = "typed_io_template_render_failed"
    TYPED_IO_TRANSCRIPT_TOO_LARGE = "typed_io_transcript_too_large"
    TYPED_IO_TRANSCRIPTION_CONFIG_INVALID = "typed_io_transcription_config_invalid"
    TYPED_IO_TRANSCRIPTION_EMPTY = "typed_io_transcription_empty"
    TYPED_IO_TRANSCRIPTION_FAILED = "typed_io_transcription_failed"
    TYPED_IO_TRANSCRIPTION_MODEL_MISSING = "typed_io_transcription_model_missing"
    TYPED_IO_TRANSCRIPTION_MODEL_UNAVAILABLE = (
        "typed_io_transcription_model_unavailable"
    )
    TYPED_IO_TRANSCRIPTION_NOT_ENABLED = "typed_io_transcription_not_enabled"
    TYPED_IO_UNSUPPORTED_TYPE = "typed_io_unsupported_type"
    PUBLISHED_FORM_SCHEMA_INVALID = "flow_published_form_schema_invalid"
    REVIEW_POLICY_INVALID = "flow_review_policy_invalid"
    REVIEW_STALE_REVISION = "flow_review_stale_revision"
    REVIEW_EXPIRED = "flow_review_expired"
    REVIEW_NOT_ACTIVE = "flow_review_not_active"
    REVIEW_STEP_RESULT_NOT_FOUND = "flow_review_step_result_not_found"
    REVIEW_CHECKPOINT_NOT_FOUND = "flow_review_checkpoint_not_found"
    REVIEW_REJECT_REASON_REQUIRED = "flow_review_reject_reason_required"
    REVIEW_REJECT_REASON_TOO_LONG = "flow_review_reject_reason_too_long"
    REVIEW_IDEMPOTENCY_KEY_REQUIRED = "flow_review_idempotency_key_required"
    REVIEW_NOT_APPROVED = "flow_review_not_approved"
    REVIEW_ALREADY_RESUMED = "flow_review_already_resumed"
    REVIEW_REJECTED = "flow_review_rejected"
    REVIEW_CANCELLED = "flow_review_cancelled"
    REVIEW_OPEN_ACTIVE_CONFLICT_INVARIANT = "flow_review_open_active_conflict_invariant"
    REVIEW_OPEN_STEP_RESULT_INCOMPLETE_INVARIANT = (
        "flow_review_open_step_result_incomplete_invariant"
    )
    REVIEW_OPEN_MULTIPLE_ACTIVE_CHECKPOINTS_INVARIANT = (
        "flow_review_open_multiple_active_checkpoints_invariant"
    )
    TEMPLATE_INVALID_ARCHIVE = "flow_template_invalid_archive"
    TEMPLATE_CORRUPTED_ARCHIVE = "flow_template_corrupted_archive"
    TEMPLATE_MACRO_NOT_ALLOWED = "flow_template_macro_not_allowed"
    TEMPLATE_MISSING_REQUIRED_PARTS = "flow_template_missing_required_parts"
    TEMPLATE_NOT_ACCESSIBLE = "flow_template_not_accessible"
    TEMPLATE_READ_ONLY = "flow_template_read_only"
    TEMPLATE_UNSUPPORTED_EXTENSION = "flow_template_unsupported_extension"
    TEMPLATE_MISSING_CONTENT = "flow_template_missing_content"
    TEMPLATE_IN_USE = "flow_template_in_use"
    RUN_RERUN_REASON_REQUIRED = "flow_run_rerun_reason_required"
    RUN_RERUN_REASON_TOO_LONG = "flow_run_rerun_reason_too_long"
    RUN_RERUN_STALE_REVISION = "flow_run_rerun_stale_revision"
    RUN_RERUN_INVALID_TRANSITION = "flow_run_rerun_invalid_transition"
    RUN_RERUN_STEP_NOT_FOUND = "flow_run_rerun_step_not_found"
    RUN_RERUN_STEP_INCOMPLETE = "flow_run_rerun_step_incomplete"
    RUN_RERUN_STEP_INPUTS_INVALID = "flow_run_rerun_step_inputs_invalid"
    RUN_RERUN_MULTIPLE_ACTIVE_OPERATIONS_INVARIANT = (
        "flow_run_rerun_multiple_active_operations_invariant"
    )
    RUN_RERUN_ATTEMPT_LINEAGE_CONFLICT_INVARIANT = (
        "flow_run_rerun_attempt_lineage_conflict_invariant"
    )


FLOW_API_ERROR_CODES: tuple[FlowApiErrorCode, ...] = tuple(FlowApiErrorCode)
FLOW_TYPED_IO_ERROR_CODES: frozenset[FlowApiErrorCode] = frozenset(
    {
        FlowApiErrorCode.LLM_REQUEST_TIMEOUT,
        FlowApiErrorCode.RUNTIME_INPUT_NOT_CONSUMED,
        FlowApiErrorCode.UNSUPPORTED_OUTPUT_MODE,
        FlowApiErrorCode.UNSUPPORTED_OUTPUT_TYPE,
        FlowApiErrorCode.TYPED_IO_CONTRACT_VIOLATION,
        FlowApiErrorCode.TYPED_IO_VALIDATION_FAILED,
        FlowApiErrorCode.TYPED_IO_VARIABLE_RESOLUTION_FAILED,
        FlowApiErrorCode.TYPED_IO_AUDIO_INVALID_FILE_TYPE,
        FlowApiErrorCode.TYPED_IO_AUDIO_MISSING_FILE,
        FlowApiErrorCode.TYPED_IO_AUDIO_SOURCE_UNSUPPORTED,
        FlowApiErrorCode.TYPED_IO_AUDIO_TOO_MANY_FILES,
        FlowApiErrorCode.TYPED_IO_DOCUMENT_SOURCE_UNSUPPORTED,
        FlowApiErrorCode.TYPED_IO_EMPTY_EXTRACTION,
        FlowApiErrorCode.TYPED_IO_FILE_NOT_FOUND,
        FlowApiErrorCode.TYPED_IO_FILE_SOURCE_UNSUPPORTED,
        FlowApiErrorCode.TYPED_IO_HTTP_CONNECTION_ERROR,
        FlowApiErrorCode.TYPED_IO_HTTP_INVALID_CONFIG,
        FlowApiErrorCode.TYPED_IO_HTTP_INVALID_URL,
        FlowApiErrorCode.TYPED_IO_HTTP_MALFORMED_RESPONSE,
        FlowApiErrorCode.TYPED_IO_HTTP_NON_SUCCESS,
        FlowApiErrorCode.TYPED_IO_HTTP_RESPONSE_TOO_LARGE,
        FlowApiErrorCode.TYPED_IO_HTTP_SSRF_BLOCKED,
        FlowApiErrorCode.TYPED_IO_HTTP_TIMEOUT,
        FlowApiErrorCode.TYPED_IO_INPUT_EXCEEDS_MODEL_WINDOW,
        FlowApiErrorCode.TYPED_IO_INPUT_TOO_LARGE,
        FlowApiErrorCode.TYPED_IO_INVALID_FILE_TYPE,
        FlowApiErrorCode.TYPED_IO_INVALID_INPUT_SOURCE_COMBINATION,
        FlowApiErrorCode.TYPED_IO_INVALID_INPUT_SOURCE_POSITION,
        FlowApiErrorCode.TYPED_IO_INVALID_JSON_INPUT,
        FlowApiErrorCode.TYPED_IO_INVALID_OUTPUT_MODE_COMBINATION,
        FlowApiErrorCode.TYPED_IO_INVALID_SCHEMA,
        FlowApiErrorCode.TYPED_IO_MISSING_REQUIRED_FILES,
        FlowApiErrorCode.TYPED_IO_OUTPUT_PARSE_FAILED,
        FlowApiErrorCode.TYPED_IO_RENDER_FAILED,
        FlowApiErrorCode.TYPED_IO_TEMPLATE_CHECKSUM_MISMATCH,
        FlowApiErrorCode.TYPED_IO_TEMPLATE_RENDER_FAILED,
        FlowApiErrorCode.TYPED_IO_TRANSCRIPT_TOO_LARGE,
        FlowApiErrorCode.TYPED_IO_TRANSCRIPTION_CONFIG_INVALID,
        FlowApiErrorCode.TYPED_IO_TRANSCRIPTION_EMPTY,
        FlowApiErrorCode.TYPED_IO_TRANSCRIPTION_FAILED,
        FlowApiErrorCode.TYPED_IO_TRANSCRIPTION_MODEL_MISSING,
        FlowApiErrorCode.TYPED_IO_TRANSCRIPTION_MODEL_UNAVAILABLE,
        FlowApiErrorCode.TYPED_IO_TRANSCRIPTION_NOT_ENABLED,
        FlowApiErrorCode.TYPED_IO_UNSUPPORTED_TYPE,
    }
)
FLOW_RUN_TERMINAL_ERROR_CODES: frozenset[FlowApiErrorCode] = frozenset(
    {
        FlowApiErrorCode.FLOW_DELETED,
        FlowApiErrorCode.RUN_CANCELLED,
        FlowApiErrorCode.RUN_USER_CANCELLED,
        FlowApiErrorCode.RUN_DISPATCH_FAILED,
        FlowApiErrorCode.RUN_MISSING_PRINCIPAL,
        FlowApiErrorCode.RUN_SERVICE_PRINCIPAL_DISABLED,
        FlowApiErrorCode.RUN_RUNTIME_ACTOR_INVALID,
        FlowApiErrorCode.RUN_TASK_TIMEOUT,
        FlowApiErrorCode.RUN_TASK_FAILURE,
        FlowApiErrorCode.RUN_WORKER_STALLED,
        FlowApiErrorCode.RUN_ERROR_PAYLOAD_INVALID,
        FlowApiErrorCode.DEFINITION_CHECKSUM_MISMATCH,
        FlowApiErrorCode.DEFINITION_INVALID,
        FlowApiErrorCode.DEFINITION_SCHEMA_VERSION_MISSING,
        FlowApiErrorCode.DEFINITION_SCHEMA_VERSION_UNSUPPORTED,
        FlowApiErrorCode.DEFINITION_FLOW_ID_INVALID,
        FlowApiErrorCode.DEFINITION_STEPS_INVALID,
        FlowApiErrorCode.DEFINITION_NO_EXECUTABLE_STEPS,
        FlowApiErrorCode.ASSISTANT_SNAPSHOT_DRIFT,
        FlowApiErrorCode.INPUT_CONTRACT_INAPPLICABLE,
        FlowApiErrorCode.STEP_MISSING,
        FlowApiErrorCode.STEP_ATTEMPT_START_FAILED,
        FlowApiErrorCode.STEP_EXECUTION_FAILED,
        FlowApiErrorCode.WEBHOOK_DELIVERY_FAILED,
        FlowApiErrorCode.REVIEW_POLICY_INVALID,
        FlowApiErrorCode.REVIEW_EXPIRED,
        FlowApiErrorCode.REVIEW_REJECTED,
        FlowApiErrorCode.REVIEW_OPEN_ACTIVE_CONFLICT_INVARIANT,
        FlowApiErrorCode.REVIEW_OPEN_STEP_RESULT_INCOMPLETE_INVARIANT,
        FlowApiErrorCode.REVIEW_OPEN_MULTIPLE_ACTIVE_CHECKPOINTS_INVARIANT,
        FlowApiErrorCode.RUN_RERUN_MULTIPLE_ACTIVE_OPERATIONS_INVARIANT,
        FlowApiErrorCode.RUN_RERUN_ATTEMPT_LINEAGE_CONFLICT_INVARIANT,
    }
    | FLOW_TYPED_IO_ERROR_CODES
)
