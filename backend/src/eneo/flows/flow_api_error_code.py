from __future__ import annotations

from enum import StrEnum, unique


@unique
class FlowApiErrorCode(StrEnum):
    """Public Flow error codes with generated SDK and localized client messages."""

    FLOW_NOT_PUBLISHED = "flow_not_published"
    REVIEW_HISTORY_TOO_LARGE = "flow_review_history_too_large"
    FLOW_DELETED = "flow_deleted"
    OWNER_REQUIRED = "flow_owner_required"
    FLOW_MANAGED_ASSISTANT = "flow_managed_assistant"
    FLOW_NAME_TAKEN = "flow_name_taken"
    SERVICE_KEY_ADMIN_REQUIRED = "flow_service_key_admin_required"
    SERVICE_KEY_PRINCIPAL_NOT_SUPPORTED = "flow_service_key_principal_not_supported"
    SERVICE_KEY_SPACE_ID_REQUIRED = "flow_service_key_space_id_required"
    RUN_INVALID_IDEMPOTENCY_KEY = "flow_run_invalid_idempotency_key"
    RUN_STALE_VERSION = "flow_run_stale_version"
    RUN_RETRY_SOURCE_NOT_FAILED = "flow_run_retry_source_not_failed"
    RUN_RETRY_SOURCE_VERSION_STALE = "flow_run_retry_source_version_stale"
    RUN_RETRY_NOTHING_TO_REUSE = "flow_run_retry_nothing_to_reuse"
    RUN_RETRY_PREFIX_UNSUPPORTED = "flow_run_retry_prefix_unsupported"
    RUN_REQUIRED_STEP_INPUT_MISSING = "flow_run_required_step_input_missing"
    DOCUMENT_RUNTIME_REQUIRED = "flow_document_runtime_required"
    STEP_READ_LOST_PRODUCER = "flow_step_read_lost_producer"
    UNPUBLISH_REQUIRED = "flow_unpublish_required"
    FORM_FIELD_STILL_READ = "flow_form_field_still_read"
    FORM_FIELD_RENAME_INVALID = "flow_form_field_rename_invalid"
    AUTHORING_CHAT_NO_MODEL = "flow_authoring_chat_no_model"
    AUTHORING_MODEL_NOT_IN_SPACE = "flow_authoring_model_not_in_space"
    AUTHORING_MODEL_BELOW_CLASSIFICATION = "flow_authoring_model_below_classification"
    AUTHORING_MODEL_WITHOUT_TOOLS = "flow_authoring_model_without_tools"
    AUTHORING_MODEL_UNAVAILABLE = "flow_authoring_model_unavailable"
    AUTHORING_REASONING_EFFORT_UNSUPPORTED = (
        "flow_authoring_reasoning_effort_unsupported"
    )
    RUN_RUNTIME_INPUT_DISABLED = "flow_run_runtime_input_disabled"
    RUN_TOP_LEVEL_FILE_IDS_NOT_SUPPORTED = "flow_run_top_level_file_ids_not_supported"
    RUN_IDEMPOTENCY_CONFLICT = "flow_run_idempotency_conflict"
    RUN_CONCURRENCY_LIMIT_REACHED = "flow_run_concurrency_limit_reached"
    RUN_REDISPATCH_CONFLICT = "flow_run_redispatch_conflict"
    RUN_REDISPATCH_AUDIT_UNAVAILABLE = "flow_run_redispatch_audit_unavailable"
    RUN_INVALID_STEP_INPUTS = "flow_run_invalid_step_inputs"
    RUN_UNKNOWN_STEP_INPUT = "flow_run_unknown_step_input"
    RUN_STEP_INPUT_MAX_FILES_EXCEEDED = "flow_run_step_input_max_files_exceeded"
    RUN_FILE_NOT_ACCESSIBLE = "flow_run_file_not_accessible"
    RUN_FILE_NOT_BOUND_TO_FLOW = "flow_run_file_not_bound_to_flow"
    RUN_FILE_ACCESS_AUDIT_UNAVAILABLE = "flow_run_file_access_audit_unavailable"
    RUN_STEP_INPUT_FILE_TOO_LARGE = "flow_run_step_input_file_too_large"
    RUN_UPLOAD_PDF_EXCEEDS_LIMIT = "flow_run_upload_pdf_exceeds_limit"
    RUN_AUDIO_EXCEEDS_LIMIT = "flow_run_audio_exceeds_limit"
    RUN_AUDIO_UNREADABLE = "flow_run_audio_unreadable"
    RUN_AUDIO_MEASUREMENT_BUSY = "flow_run_audio_measurement_busy"
    RUN_STEP_INPUT_MIMETYPE_REJECTED = "flow_run_step_input_mimetype_rejected"
    RUN_AGGREGATE_MAX_FILES_EXCEEDED = "flow_run_aggregate_max_files_exceeded"
    RUN_RESERVED_INPUT_PAYLOAD_KEY = "flow_run_reserved_input_payload_key"
    RUN_SPEAKER_LABELS_NOT_SELECTABLE = "flow_run_speaker_labels_not_selectable"
    RUN_MAX_SPEAKERS_NOT_AVAILABLE = "flow_run_max_speakers_not_available"
    RUN_INVALID_LABEL = "flow_run_invalid_label"
    RUN_INPUT_PAYLOAD_TOO_LARGE = "flow_run_input_payload_too_large"
    RUN_INPUT_EXCEEDS_LIMIT = "flow_run_input_exceeds_limit"
    INPUT_REQUIRED_FIELD_MISSING = "flow_input_required_field_missing"
    INPUT_REQUIRED_FIELD_EMPTY = "flow_input_required_field_empty"
    INPUT_TYPE_MISMATCH = "flow_input_type_mismatch"
    INPUT_INVALID_NUMBER = "flow_input_invalid_number"
    INPUT_INVALID_DATE = "flow_input_invalid_date"
    INPUT_INVALID_OPTION = "flow_input_invalid_option"
    INPUT_INVALID_MULTISELECT_VALUE = "flow_input_invalid_multiselect_value"
    INPUT_INVALID_MULTISELECT_TYPE = "flow_input_invalid_multiselect_type"
    INPUT_INVALID_LIST_VALUE = "flow_input_invalid_list_value"
    INPUT_INVALID_LIST_TYPE = "flow_input_invalid_list_type"
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
    RUN_WORKER_SHUTDOWN = "flow_worker_shutdown"
    RUN_ABANDONED = "flow_run_abandoned"
    RUN_ERROR_PAYLOAD_INVALID = "flow_run_error_payload_invalid"
    RUN_EVIDENCE_FORBIDDEN = "flow_run_evidence_forbidden"
    RUN_EVIDENCE_EXPORT_DISABLED = "flow_run_evidence_export_disabled"
    RUN_EVIDENCE_RAW_EXPORT_FORBIDDEN = "flow_run_evidence_raw_export_forbidden"
    RUN_ARTIFACT_NOT_FOUND = "flow_run_artifact_not_found"
    RUN_ARTIFACT_CONTENT_UNAVAILABLE = "flow_run_artifact_content_unavailable"
    RUN_INPUT_FILE_NOT_FOUND = "flow_run_input_file_not_found"
    RUN_INPUT_FILE_CONTENT_UNAVAILABLE = "flow_run_input_file_content_unavailable"
    DEFINITION_CHECKSUM_MISMATCH = "flow_definition_checksum_mismatch"
    DEFINITION_INVALID = "flow_definition_invalid"
    DEFINITION_SCHEMA_VERSION_MISSING = "flow_definition_schema_version_missing"
    DEFINITION_SCHEMA_VERSION_UNSUPPORTED = "flow_definition_schema_version_unsupported"
    DEFINITION_FLOW_ID_INVALID = "flow_definition_flow_id_invalid"
    DEFINITION_STEPS_INVALID = "flow_definition_steps_invalid"
    DEFINITION_NO_EXECUTABLE_STEPS = "flow_definition_no_executable_steps"
    ASSISTANT_MODEL_PROVIDER_REQUIRED = "flow_assistant_model_provider_required"
    ASSISTANT_SNAPSHOT_REPUBLISH_REQUIRED = "flow_assistant_snapshot_republish_required"
    ASSISTANT_SNAPSHOT_DRIFT = "flow_assistant_snapshot_drift"
    INPUT_CONTRACT_INAPPLICABLE = "flow_input_contract_inapplicable"
    STEP_LIMIT_EXCEEDED = "flow_step_limit_exceeded"
    REQUEST_BODY_TOO_LARGE = "flow_request_body_too_large"
    STEP_SECURITY_CLASSIFICATION_MISMATCH = "flow_step_security_classification_mismatch"
    STEP_OUTPUT_CLASSIFICATION_WRITE_DOWN = "flow_step_output_classification_write_down"
    STEP_TOOL_ARGUMENTS_CLASSIFICATION_WRITE_DOWN = (
        "flow_step_tool_arguments_classification_write_down"
    )
    STEP_MISSING = "flow_step_missing"
    STEP_ATTEMPT_START_FAILED = "flow_step_attempt_start_failed"
    STEP_EXECUTION_FAILED = "flow_step_execution_failed"
    PROVIDER_RATE_LIMITED = "flow_provider_rate_limited"
    PROVIDER_UNAVAILABLE = "flow_provider_unavailable"
    PROVIDER_CALL_EVIDENCE_PERSISTENCE_FAILED = (
        "flow_provider_call_evidence_persistence_failed"
    )
    WEBHOOK_DELIVERY_FAILED = "flow_webhook_delivery_failed"
    RUNTIME_FILE_EMPTY = "flow_runtime_file_empty"
    RUNTIME_FILE_ATTACHED = "flow_runtime_file_attached"
    LIVE_TRANSCRIPTION_UNAVAILABLE = "flow_live_transcription_unavailable"
    RUN_LIVE_TRANSCRIPT_REQUIRES_ONE_AUDIO_FILE = (
        "flow_run_live_transcript_requires_one_audio_file"
    )
    RUN_LIVE_TRANSCRIPT_NOT_FOUND = "flow_run_live_transcript_not_found"
    RUN_SINGLE_RECORDING_REQUIRES_AUDIO_STEP = (
        "flow_run_single_recording_requires_audio_step"
    )
    RUN_LIVE_TRANSCRIPT_ALREADY_BOUND = "flow_run_live_transcript_already_bound"
    EVIDENCE_AUDIT_LOGGING_FAILED = "flow_evidence_audit_logging_failed"
    EVIDENCE_EXPORT_REASON_REQUIRED = "flow_evidence_export_reason_required"
    EVIDENCE_EXPORT_TOO_LARGE = "flow_evidence_export_too_large"
    MODEL_CAPACITY_UNDECLARED = "flow_model_capacity_undeclared"
    LLM_OUTPUT_TRUNCATED = "flow_llm_output_truncated"
    LLM_OUTPUT_WHITESPACE_ABORT = "flow_llm_output_whitespace_abort"
    LLM_REQUEST_TIMEOUT = "flow_llm_request_timeout"
    STEP_TIMEOUT = "flow_step_timeout"
    STEP_TIMEOUT_EXCEEDS_TENANT_MAX = "flow_step_timeout_exceeds_tenant_max"
    RUNTIME_INPUT_NOT_CONSUMED = "flow_runtime_input_not_consumed"
    MAPPED_PROVIDER_CALL_LIMIT_EXCEEDED = "flow_mapped_provider_call_limit_exceeded"
    SUMMARIZATION_NON_CONVERGENT = "flow_summarization_non_convergent"
    LONG_MATERIAL_PARTIAL_COVERAGE = "flow_long_material_partial_coverage"
    UNSUPPORTED_OUTPUT_MODE = "flow_unsupported_output_mode"
    UNSUPPORTED_OUTPUT_TYPE = "flow_unsupported_output_type"
    TYPED_IO_CONTRACT_VIOLATION = "typed_io_contract_violation"
    TYPED_IO_CONTRACT_NOT_CHECKED = "typed_io_contract_not_checked"
    TYPED_IO_VALIDATION_FAILED = "typed_io_validation_failed"
    TYPED_IO_VARIABLE_RESOLUTION_FAILED = "typed_io_variable_resolution_failed"
    TYPED_IO_AUDIO_INVALID_FILE_TYPE = "typed_io_audio_invalid_file_type"
    TYPED_IO_AUDIO_MISSING_FILE = "typed_io_audio_missing_file"
    TYPED_IO_AUDIO_SOURCE_UNSUPPORTED = "typed_io_audio_source_unsupported"
    TYPED_IO_AUDIO_TOO_MANY_FILES = "typed_io_audio_too_many_files"
    TYPED_IO_AUDIO_EXCEEDS_LIMIT = "typed_io_audio_exceeds_limit"
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
    TYPED_IO_TOOL_ANSWER_TOO_LARGE = "typed_io_tool_answer_too_large"
    TYPED_IO_TOOL_CHANGED = "typed_io_tool_changed"
    TYPED_IO_TOOL_CLASSIFICATION_CHANGED = "typed_io_tool_classification_changed"
    TYPED_IO_TOOL_CONNECTION_ERROR = "typed_io_tool_connection_error"
    TYPED_IO_TOOL_DESTINATION_BLOCKED = "typed_io_tool_destination_blocked"
    TYPED_IO_TOOL_INVALID_ARGUMENTS = "typed_io_tool_invalid_arguments"
    TYPED_IO_TOOL_INVALID_CONFIG = "typed_io_tool_invalid_config"
    TYPED_IO_TOOL_INVALID_SCHEMA = "typed_io_tool_invalid_schema"
    TYPED_IO_TOOL_MALFORMED_ANSWER = "typed_io_tool_malformed_answer"
    TYPED_IO_TOOL_NOT_ALLOWED = "typed_io_tool_not_allowed"
    TYPED_IO_TOOL_REPORTED_ERROR = "typed_io_tool_reported_error"
    TYPED_IO_TOOL_TIMEOUT = "typed_io_tool_timeout"
    TYPED_IO_INPUT_EXCEEDS_MODEL_WINDOW = "typed_io_input_exceeds_model_window"
    TYPED_IO_INPUT_TOO_LARGE = "typed_io_input_too_large"
    TYPED_IO_STRUCTURED_OUTPUT_EXCEEDS_LIMIT = (
        "typed_io_structured_output_exceeds_limit"
    )
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
    TYPED_IO_SPEAKER_IDENTIFICATION_FAILED = "typed_io_speaker_identification_failed"
    TYPED_IO_TRANSCRIPTION_MODEL_MISSING = "typed_io_transcription_model_missing"
    TYPED_IO_TRANSCRIPTION_MODEL_UNAVAILABLE = (
        "typed_io_transcription_model_unavailable"
    )
    TYPED_IO_SPEAKER_SERVICE_UNAVAILABLE = "typed_io_speaker_service_unavailable"
    TYPED_IO_TRANSCRIPTION_NOT_ENABLED = "typed_io_transcription_not_enabled"
    TYPED_IO_UNSUPPORTED_TYPE = "typed_io_unsupported_type"
    PUBLISHED_FORM_SCHEMA_INVALID = "flow_published_form_schema_invalid"
    REVIEW_POLICY_INVALID = "flow_review_policy_invalid"
    REVIEW_STALE_REVISION = "flow_review_stale_revision"
    REVIEW_EXPIRED = "flow_review_expired"
    REVIEW_NOT_ACTIVE = "flow_review_not_active"
    REVIEW_STEP_RESULT_NOT_FOUND = "flow_review_step_result_not_found"
    REVIEW_EDIT_NOT_ALLOWED = "flow_review_edit_not_allowed"
    REVIEW_EDIT_FILE_BACKED_UNSUPPORTED = "flow_review_edit_file_backed_unsupported"
    REVIEW_EDIT_OUTPUT_TOO_LARGE = "flow_review_edit_output_too_large"
    REVIEW_CHECKPOINT_NOT_FOUND = "flow_review_checkpoint_not_found"
    REVIEW_REJECT_REASON_REQUIRED = "flow_review_reject_reason_required"
    REVIEW_REJECT_REASON_TOO_LONG = "flow_review_reject_reason_too_long"
    REVIEW_IDEMPOTENCY_KEY_REQUIRED = "flow_review_idempotency_key_required"
    REVIEW_NOT_APPROVED = "flow_review_not_approved"
    REVIEW_ALREADY_RESUMED = "flow_review_already_resumed"
    REVIEW_REJECTED = "flow_review_rejected"
    REVIEW_CANCELLED = "flow_review_cancelled"
    TRANSCRIPT_CORRECTIONS_STALE_REVISION = "flow_transcript_corrections_stale_revision"
    TRANSCRIPT_CORRECTIONS_SEGMENTS_UNAVAILABLE = (
        "flow_transcript_corrections_segments_unavailable"
    )
    TRANSCRIPT_CORRECTIONS_INVALID_OCCURRENCE = (
        "flow_transcript_corrections_invalid_occurrence"
    )
    TRANSCRIPT_CORRECTIONS_INVALID_SPEAKER_EDIT = (
        "flow_transcript_corrections_invalid_speaker_edit"
    )
    REVIEW_OPEN_ACTIVE_CONFLICT_INVARIANT = "flow_review_open_active_conflict_invariant"
    REVIEW_OPEN_STEP_RESULT_INCOMPLETE_INVARIANT = (
        "flow_review_open_step_result_incomplete_invariant"
    )
    REVIEW_OPEN_MULTIPLE_ACTIVE_CHECKPOINTS_INVARIANT = (
        "flow_review_open_multiple_active_checkpoints_invariant"
    )
    TEMPLATE_INVALID_ARCHIVE = "flow_template_invalid_archive"
    TEMPLATE_NO_CONTROLS = "flow_template_no_controls"
    TEMPLATE_CONTROL_UNTAGGED = "flow_template_control_untagged"
    TEMPLATE_CONTROL_PLACEMENT = "flow_template_control_placement"
    TEMPLATE_CONTROL_NESTED = "flow_template_control_nested"
    TEMPLATE_CONTROL_MAPPED = "flow_template_control_mapped"
    TEMPLATE_CONTROL_UNSUPPORTED = "flow_template_control_unsupported"
    TEMPLATE_CONTROL_DUPLICATE = "flow_template_control_duplicate"
    TEMPLATE_CORRUPTED_ARCHIVE = "flow_template_corrupted_archive"
    TEMPLATE_MACRO_NOT_ALLOWED = "flow_template_macro_not_allowed"
    TEMPLATE_MISSING_REQUIRED_PARTS = "flow_template_missing_required_parts"
    TEMPLATE_NOT_ACCESSIBLE = "flow_template_not_accessible"
    TEMPLATE_READ_ONLY = "flow_template_read_only"
    TEMPLATE_UNSUPPORTED_EXTENSION = "flow_template_unsupported_extension"
    TEMPLATE_MISSING_CONTENT = "flow_template_missing_content"
    TEMPLATE_IN_USE = "flow_template_in_use"
    TEMPLATE_DOWNLOAD_AUDIT_UNAVAILABLE = "flow_template_download_audit_unavailable"
    PACKAGE_EXPORT_AUDIT_UNAVAILABLE = "flow_package_export_audit_unavailable"

    ASSISTANT_SNAPSHOT_RESOURCE_INVALID = "flow_assistant_snapshot_resource_invalid"

    MAPPED_EXECUTION_PUBLISHED_CEILING_REQUIRED = (
        "flow_mapped_execution_published_ceiling_required"
    )
    SETTINGS_INVALID_PAYLOAD = "flow_settings_invalid_payload"
    STEP_NAME_RESERVED_VARIABLE = "flow_step_name_reserved_variable"
    STEP_NAME_STEP_ALIAS = "flow_step_name_step_alias"
    TEMPLATE_TOO_LARGE = "flow_template_too_large"
    DEFAULT_TIMEOUT_EXCEEDS_TENANT_MAX = "default_timeout_exceeds_tenant_max"
    MAX_CONCURRENT_RUNS_EXCEEDS_SERVER_CAPACITY = (
        "max_concurrent_runs_exceeds_server_capacity"
    )
    TENANT_MAX_EXCEEDS_ENV_HARD_CEILING = "tenant_max_exceeds_env_hard_ceiling"
    FORM_FIELD_NAME_NAMESPACE_HEAD = "flow_form_field_name_namespace_head"
    FORM_FIELD_NAME_PRIMARY_INPUT_KEY = "flow_form_field_name_primary_input_key"
    FORM_FIELD_NAME_STEP_ALIAS = "flow_form_field_name_step_alias"
    FORM_FIELD_NAME_EMPTY = "flow_form_field_name_empty"
    FORM_FIELD_NAME_DUPLICATE = "flow_form_field_name_duplicate"
    FORM_FIELD_NAME_DOT = "flow_form_field_name_dot"
    FORM_FIELD_NAME_TEMPLATE_DELIMITERS = "flow_form_field_name_template_delimiters"
    TOOL_OPTIONS_TOO_LARGE = "flow_tool_options_too_large"

    STALE_REVISION = "stale_revision"
    UNKNOWN_STEP_ID = "unknown_step_id"
    DUPLICATE_STEP_ID = "duplicate_step_id"
    SENTINEL_SECRET_REQUIRES_STEP_ID = "sentinel_secret_requires_step_id"
    UNSUPPORTED_MEDIA_TYPE = "unsupported_media_type"


FLOW_API_ERROR_CODES: tuple[FlowApiErrorCode, ...] = tuple(FlowApiErrorCode)
FLOW_TYPED_IO_ERROR_CODES: frozenset[FlowApiErrorCode] = frozenset(
    {
        FlowApiErrorCode.RUN_INPUT_EXCEEDS_LIMIT,
        FlowApiErrorCode.TYPED_IO_STRUCTURED_OUTPUT_EXCEEDS_LIMIT,
        FlowApiErrorCode.MODEL_CAPACITY_UNDECLARED,
        FlowApiErrorCode.LLM_OUTPUT_TRUNCATED,
        FlowApiErrorCode.LLM_OUTPUT_WHITESPACE_ABORT,
        FlowApiErrorCode.LLM_REQUEST_TIMEOUT,
        FlowApiErrorCode.STEP_TIMEOUT,
        FlowApiErrorCode.STEP_TIMEOUT_EXCEEDS_TENANT_MAX,
        FlowApiErrorCode.RUNTIME_INPUT_NOT_CONSUMED,
        FlowApiErrorCode.MAPPED_PROVIDER_CALL_LIMIT_EXCEEDED,
        FlowApiErrorCode.SUMMARIZATION_NON_CONVERGENT,
        FlowApiErrorCode.LONG_MATERIAL_PARTIAL_COVERAGE,
        FlowApiErrorCode.UNSUPPORTED_OUTPUT_MODE,
        FlowApiErrorCode.UNSUPPORTED_OUTPUT_TYPE,
        FlowApiErrorCode.TYPED_IO_CONTRACT_VIOLATION,
        FlowApiErrorCode.TYPED_IO_CONTRACT_NOT_CHECKED,
        FlowApiErrorCode.TYPED_IO_VALIDATION_FAILED,
        FlowApiErrorCode.TYPED_IO_VARIABLE_RESOLUTION_FAILED,
        FlowApiErrorCode.TYPED_IO_AUDIO_INVALID_FILE_TYPE,
        FlowApiErrorCode.TYPED_IO_AUDIO_MISSING_FILE,
        FlowApiErrorCode.TYPED_IO_AUDIO_SOURCE_UNSUPPORTED,
        FlowApiErrorCode.TYPED_IO_AUDIO_TOO_MANY_FILES,
        FlowApiErrorCode.TYPED_IO_AUDIO_EXCEEDS_LIMIT,
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
        FlowApiErrorCode.TYPED_IO_TOOL_ANSWER_TOO_LARGE,
        FlowApiErrorCode.TYPED_IO_TOOL_CHANGED,
        FlowApiErrorCode.TYPED_IO_TOOL_CLASSIFICATION_CHANGED,
        FlowApiErrorCode.TYPED_IO_TOOL_CONNECTION_ERROR,
        FlowApiErrorCode.TYPED_IO_TOOL_DESTINATION_BLOCKED,
        FlowApiErrorCode.TYPED_IO_TOOL_INVALID_ARGUMENTS,
        FlowApiErrorCode.TYPED_IO_TOOL_INVALID_CONFIG,
        FlowApiErrorCode.TYPED_IO_TOOL_INVALID_SCHEMA,
        FlowApiErrorCode.TYPED_IO_TOOL_MALFORMED_ANSWER,
        FlowApiErrorCode.TYPED_IO_TOOL_NOT_ALLOWED,
        FlowApiErrorCode.TYPED_IO_TOOL_REPORTED_ERROR,
        FlowApiErrorCode.TYPED_IO_TOOL_TIMEOUT,
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
        FlowApiErrorCode.TYPED_IO_SPEAKER_IDENTIFICATION_FAILED,
        FlowApiErrorCode.TYPED_IO_TRANSCRIPTION_MODEL_MISSING,
        FlowApiErrorCode.TYPED_IO_TRANSCRIPTION_MODEL_UNAVAILABLE,
        FlowApiErrorCode.TYPED_IO_SPEAKER_SERVICE_UNAVAILABLE,
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
        FlowApiErrorCode.RUN_WORKER_SHUTDOWN,
        FlowApiErrorCode.RUN_ABANDONED,
        FlowApiErrorCode.RUN_ERROR_PAYLOAD_INVALID,
        FlowApiErrorCode.DEFINITION_CHECKSUM_MISMATCH,
        FlowApiErrorCode.DEFINITION_INVALID,
        FlowApiErrorCode.DEFINITION_SCHEMA_VERSION_MISSING,
        FlowApiErrorCode.DEFINITION_SCHEMA_VERSION_UNSUPPORTED,
        FlowApiErrorCode.DEFINITION_FLOW_ID_INVALID,
        FlowApiErrorCode.DEFINITION_STEPS_INVALID,
        FlowApiErrorCode.DEFINITION_NO_EXECUTABLE_STEPS,
        FlowApiErrorCode.ASSISTANT_MODEL_PROVIDER_REQUIRED,
        FlowApiErrorCode.ASSISTANT_SNAPSHOT_REPUBLISH_REQUIRED,
        FlowApiErrorCode.ASSISTANT_SNAPSHOT_DRIFT,
        FlowApiErrorCode.ASSISTANT_SNAPSHOT_RESOURCE_INVALID,
        FlowApiErrorCode.INPUT_CONTRACT_INAPPLICABLE,
        FlowApiErrorCode.STEP_MISSING,
        FlowApiErrorCode.STEP_ATTEMPT_START_FAILED,
        FlowApiErrorCode.STEP_EXECUTION_FAILED,
        FlowApiErrorCode.PROVIDER_RATE_LIMITED,
        FlowApiErrorCode.PROVIDER_UNAVAILABLE,
        FlowApiErrorCode.PROVIDER_CALL_EVIDENCE_PERSISTENCE_FAILED,
        FlowApiErrorCode.WEBHOOK_DELIVERY_FAILED,
        FlowApiErrorCode.REVIEW_POLICY_INVALID,
        FlowApiErrorCode.REVIEW_EXPIRED,
        FlowApiErrorCode.REVIEW_REJECTED,
        FlowApiErrorCode.REVIEW_OPEN_ACTIVE_CONFLICT_INVARIANT,
        FlowApiErrorCode.REVIEW_OPEN_STEP_RESULT_INCOMPLETE_INVARIANT,
        FlowApiErrorCode.REVIEW_OPEN_MULTIPLE_ACTIVE_CHECKPOINTS_INVARIANT,
    }
    | FLOW_TYPED_IO_ERROR_CODES
)
# The codes after which a new logical run repeats no accepted provider work.
# The code alone does not say whether a tool was called: a run error the
# executor writes at or after a tool step, and one the dispatcher writes for
# a run that has completed a tool step, carries that as a typed fact
# (FlowRunErrorDetails.tool_call_possible), and FlowRunError.retryable is this
# entry and not that fact. Lifecycle drift must revisit this allowlist.
FLOW_RUN_TERMINAL_ERROR_RETRYABILITY: dict[FlowApiErrorCode, bool] = {
    code: code
    in {
        FlowApiErrorCode.RUN_DISPATCH_FAILED,
        FlowApiErrorCode.STEP_ATTEMPT_START_FAILED,
        FlowApiErrorCode.PROVIDER_RATE_LIMITED,
    }
    for code in FLOW_RUN_TERMINAL_ERROR_CODES
}


def typed_io_failure_code(raw_code: str | None) -> FlowApiErrorCode:
    """The typed input/output code a typed step failure ends with: its own
    code when it is one, else ``typed_io_validation_failed``."""
    if raw_code is None:
        return FlowApiErrorCode.TYPED_IO_VALIDATION_FAILED
    try:
        code = FlowApiErrorCode(raw_code)
    except ValueError:
        return FlowApiErrorCode.TYPED_IO_VALIDATION_FAILED
    if code in FLOW_TYPED_IO_ERROR_CODES:
        return code
    return FlowApiErrorCode.TYPED_IO_VALIDATION_FAILED
