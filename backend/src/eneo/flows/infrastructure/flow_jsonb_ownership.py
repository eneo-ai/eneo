from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class FlowJsonbStorageCategory(StrEnum):
    AUTHORED_CONFIG = "authored_config"
    IMMUTABLE_SNAPSHOT = "immutable_snapshot"
    RUNTIME_PAYLOAD = "runtime_payload"
    REVIEW_CHECKPOINT = "review_checkpoint"
    RERUN_STATE = "rerun_state"
    PROVENANCE_EVIDENCE = "provenance_evidence"
    IMPORT_STATE = "import_state"
    DERIVED_INDEX = "derived_index"
    BUILDER_SESSION_STATE = "builder_session_state"


class FlowJsonbSchemaVersionPolicy(StrEnum):
    EMBEDDED_SCHEMA_VERSION = "embedded_schema_version"
    TABLE_SCHEMA_VERSION = "table_schema_version"
    CHECKSUMMED_SNAPSHOT = "checksummed_snapshot"
    OWNER_VALIDATED_SHAPE = "owner_validated_shape"
    PROVIDER_DEFINED = "provider_defined"


class FlowJsonbCorruptionBehavior(StrEnum):
    REJECT_BEFORE_WRITE = "reject_before_write"
    FAIL_RUN_OR_STEP = "fail_run_or_step"
    FAIL_SESSION_LOAD = "fail_session_load"
    FAIL_PLAN_LOAD = "fail_plan_load"
    KEEP_AUDITABLE_FAILURE = "keep_auditable_failure"
    MARK_EVIDENCE_UNAVAILABLE = "mark_evidence_unavailable"
    NORMALIZE_TO_EMPTY = "normalize_to_empty"


@dataclass(frozen=True, slots=True)
class FlowJsonbColumnOwner:
    table_name: str
    column_name: str
    owner_module: str
    envelope_name: str
    owner_symbols: tuple[str, ...]
    storage_category: FlowJsonbStorageCategory
    schema_version_policy: str
    corruption_behavior: str
    rationale: str

    @property
    def key(self) -> tuple[str, str]:
        return self.table_name, self.column_name


def build_flow_jsonb_owner_map(
    entries: tuple[FlowJsonbColumnOwner, ...],
) -> dict[tuple[str, str], FlowJsonbColumnOwner]:
    owners: dict[tuple[str, str], FlowJsonbColumnOwner] = {}
    for entry in entries:
        if entry.key in owners:
            table_name, column_name = entry.key
            raise ValueError(
                f"Duplicate Flow JSONB ownership entry for {table_name}.{column_name}"
            )
        owners[entry.key] = entry
    return owners


def _owner(
    table_name: str,
    column_name: str,
    *,
    owner_module: str,
    envelope_name: str,
    owner_symbols: tuple[str, ...] = (),
    storage_category: FlowJsonbStorageCategory,
    schema_version_policy: str,
    corruption_behavior: str,
    rationale: str,
) -> FlowJsonbColumnOwner:
    return FlowJsonbColumnOwner(
        table_name=table_name,
        column_name=column_name,
        owner_module=owner_module,
        envelope_name=envelope_name,
        owner_symbols=owner_symbols,
        storage_category=storage_category,
        schema_version_policy=schema_version_policy,
        corruption_behavior=corruption_behavior,
        rationale=rationale,
    )


FLOW_JSONB_COLUMN_OWNER_ENTRIES: tuple[FlowJsonbColumnOwner, ...] = (
    _owner(
        "tenants",
        "flow_settings",
        owner_module="eneo.flows.flow_settings",
        envelope_name="TenantFlowSettings",
        owner_symbols=(
            "normalize_flow_settings_object",
            "validate_flow_settings_write",
            "validate_flow_settings_object",
        ),
        storage_category=FlowJsonbStorageCategory.AUTHORED_CONFIG,
        schema_version_policy=FlowJsonbSchemaVersionPolicy.OWNER_VALIDATED_SHAPE,
        corruption_behavior=FlowJsonbCorruptionBehavior.REJECT_BEFORE_WRITE,
        rationale=(
            "Tenant Flow settings are one bounded object whose top-level keys and "
            "nested policies are normalized on read and validated before writes."
        ),
    ),
    _owner(
        "flows",
        "metadata_json",
        owner_module="eneo.flows.flow_metadata",
        envelope_name="FlowMetadata",
        owner_symbols=(
            "FlowMetadata",
            "parse_flow_metadata",
            "serialize_flow_metadata",
        ),
        storage_category=FlowJsonbStorageCategory.AUTHORED_CONFIG,
        schema_version_policy=FlowJsonbSchemaVersionPolicy.OWNER_VALIDATED_SHAPE,
        corruption_behavior=FlowJsonbCorruptionBehavior.NORMALIZE_TO_EMPTY,
        rationale=(
            "Sparse authoring metadata changes independently from the core Flow "
            "row and is normalized by the Flow metadata parser before use."
        ),
    ),
    _owner(
        "flow_steps",
        "input_contract",
        owner_module="eneo.flows.runtime.step_definition_parser",
        envelope_name="StepInputContract",
        owner_symbols=(
            "_parse_input_fields",
            "_validate_input_contract_binding_compatibility",
        ),
        storage_category=FlowJsonbStorageCategory.AUTHORED_CONFIG,
        schema_version_policy=FlowJsonbSchemaVersionPolicy.OWNER_VALIDATED_SHAPE,
        corruption_behavior=FlowJsonbCorruptionBehavior.REJECT_BEFORE_WRITE,
        rationale=(
            "Step input contracts are authored per step and validated into the "
            "published runtime definition rather than queried relationally."
        ),
    ),
    _owner(
        "flow_steps",
        "output_contract",
        owner_module="eneo.flows.runtime.step_definition_parser",
        envelope_name="StepOutputContract",
        owner_symbols=("_parse_output_fields",),
        storage_category=FlowJsonbStorageCategory.AUTHORED_CONFIG,
        schema_version_policy=FlowJsonbSchemaVersionPolicy.OWNER_VALIDATED_SHAPE,
        corruption_behavior=FlowJsonbCorruptionBehavior.REJECT_BEFORE_WRITE,
        rationale=(
            "Output contracts are structured step configuration whose fields "
            "vary by output mode and are validated before publish."
        ),
    ),
    _owner(
        "flow_steps",
        "input_bindings",
        owner_module="eneo.flows.runtime.step_definition_parser",
        envelope_name="StepInputBindings",
        owner_symbols=(
            "_parse_input_fields",
            "_validate_supported_input_binding_keys",
        ),
        storage_category=FlowJsonbStorageCategory.AUTHORED_CONFIG,
        schema_version_policy=FlowJsonbSchemaVersionPolicy.OWNER_VALIDATED_SHAPE,
        corruption_behavior=FlowJsonbCorruptionBehavior.REJECT_BEFORE_WRITE,
        rationale=(
            "Bindings are authored graph references with mode-specific shapes; "
            "keeping them in JSON avoids artificial join tables for sparse forms."
        ),
    ),
    _owner(
        "flow_steps",
        "input_config",
        owner_module="eneo.flows.runtime.step_definition_parser",
        envelope_name="StepInputConfig",
        owner_symbols=("_parse_input_config",),
        storage_category=FlowJsonbStorageCategory.AUTHORED_CONFIG,
        schema_version_policy=FlowJsonbSchemaVersionPolicy.OWNER_VALIDATED_SHAPE,
        corruption_behavior=FlowJsonbCorruptionBehavior.REJECT_BEFORE_WRITE,
        rationale=(
            "Input configuration is a mode-specific envelope validated at the "
            "authoring boundary and read as part of the step definition."
        ),
    ),
    _owner(
        "flow_steps",
        "output_config",
        owner_module="eneo.flows.runtime.step_definition_parser",
        envelope_name="StepOutputConfig",
        owner_symbols=("_parse_output_config",),
        storage_category=FlowJsonbStorageCategory.AUTHORED_CONFIG,
        schema_version_policy=FlowJsonbSchemaVersionPolicy.OWNER_VALIDATED_SHAPE,
        corruption_behavior=FlowJsonbCorruptionBehavior.REJECT_BEFORE_WRITE,
        rationale=(
            "Output configuration is sparse and output-mode specific, so the "
            "typed parser is the correct boundary instead of relational tables."
        ),
    ),
    _owner(
        "flow_steps",
        "review_policy",
        owner_module="eneo.flows.flow_review_policy",
        envelope_name="FlowReviewPolicy",
        owner_symbols=(
            "FlowStepReviewPolicy",
            "parse_flow_step_review_policy",
            "dump_flow_step_review_policy",
        ),
        storage_category=FlowJsonbStorageCategory.AUTHORED_CONFIG,
        schema_version_policy=FlowJsonbSchemaVersionPolicy.OWNER_VALIDATED_SHAPE,
        corruption_behavior=FlowJsonbCorruptionBehavior.REJECT_BEFORE_WRITE,
        rationale=(
            "Review policy is optional per step and parsed into a typed policy "
            "before it can pause runtime execution."
        ),
    ),
    _owner(
        "flow_versions",
        "definition_json",
        owner_module="eneo.flows.published_definition",
        envelope_name="PublishedFlowDefinition",
        owner_symbols=(
            "PublishedFlowDefinition",
            "build_published_definition_json",
            "parse_verified_published_definition",
            "inspect_published_definition_integrity",
        ),
        storage_category=FlowJsonbStorageCategory.IMMUTABLE_SNAPSHOT,
        schema_version_policy=FlowJsonbSchemaVersionPolicy.CHECKSUMMED_SNAPSHOT,
        corruption_behavior=FlowJsonbCorruptionBehavior.KEEP_AUDITABLE_FAILURE,
        rationale=(
            "Published definitions are immutable, checksummed snapshots of the "
            "runtime contract. Functional reads fail closed through the verified "
            "parser, while authorized evidence retains the raw snapshot as an "
            "auditable invalid artifact."
        ),
    ),
    _owner(
        "flow_template_assets",
        "placeholders",
        owner_module="eneo.flows.flow_template_asset_service",
        envelope_name="TemplateAssetPlaceholders",
        owner_symbols=("_unique_placeholder_names",),
        storage_category=FlowJsonbStorageCategory.DERIVED_INDEX,
        schema_version_policy=FlowJsonbSchemaVersionPolicy.OWNER_VALIDATED_SHAPE,
        corruption_behavior=FlowJsonbCorruptionBehavior.REJECT_BEFORE_WRITE,
        rationale=(
            "Extracted placeholder names are a small derived index for template "
            "validation and do not need row identity of their own."
        ),
    ),
    _owner(
        "flow_package_imports",
        "import_plan_json",
        owner_module="eneo.flow_packages.domain.flow_package_import_plan",
        envelope_name="FlowPackageImportPlan",
        owner_symbols=("FlowPackageImportPlan",),
        storage_category=FlowJsonbStorageCategory.IMPORT_STATE,
        schema_version_policy=FlowJsonbSchemaVersionPolicy.OWNER_VALIDATED_SHAPE,
        corruption_behavior=FlowJsonbCorruptionBehavior.REJECT_BEFORE_WRITE,
        rationale=(
            "Import plans are owner-validated auditable snapshots of the exact "
            "portable package and destination decision; computed API fields are "
            "not persisted and the JSON is not a replay contract."
        ),
    ),
    _owner(
        "flow_package_imports",
        "selected_mappings_json",
        owner_module="eneo.flow_packages.domain.flow_package_import_record",
        envelope_name="FlowPackageSelectedMappings",
        owner_symbols=("FlowPackageImportSelection",),
        storage_category=FlowJsonbStorageCategory.IMPORT_STATE,
        schema_version_policy=FlowJsonbSchemaVersionPolicy.OWNER_VALIDATED_SHAPE,
        corruption_behavior=FlowJsonbCorruptionBehavior.REJECT_BEFORE_WRITE,
        rationale=(
            "Selected mappings preserve the user's import choices for audit and "
            "replay without introducing package-specific relational tables."
        ),
    ),
    _owner(
        "flow_package_imports",
        "failure_json",
        owner_module="eneo.flow_packages.domain.flow_package_import_record",
        envelope_name="FlowPackageImportFailure",
        owner_symbols=("FlowPackageImportFailurePayload",),
        storage_category=FlowJsonbStorageCategory.IMPORT_STATE,
        schema_version_policy=FlowJsonbSchemaVersionPolicy.OWNER_VALIDATED_SHAPE,
        corruption_behavior=FlowJsonbCorruptionBehavior.KEEP_AUDITABLE_FAILURE,
        rationale=(
            "Failed imports need a structured failure snapshot while preserving "
            "the terminal import row for audit."
        ),
    ),
    _owner(
        "flow_runs",
        "input_payload_json",
        owner_module="eneo.flows.flow_run_input_envelope",
        envelope_name="FlowRunInputEnvelope",
        owner_symbols=(
            "build_initial_run_input_envelope",
            "read_semantic_flow_input_payload",
        ),
        storage_category=FlowJsonbStorageCategory.RUNTIME_PAYLOAD,
        schema_version_policy=FlowJsonbSchemaVersionPolicy.OWNER_VALIDATED_SHAPE,
        corruption_behavior=FlowJsonbCorruptionBehavior.FAIL_RUN_OR_STEP,
        rationale=(
            "Run input is caller-provided execution data with variable keys; the "
            "input envelope owns reserved keys and file binding semantics."
        ),
    ),
    _owner(
        "flow_runs",
        "output_payload_json",
        owner_module="eneo.flows.runtime.run_outcome",
        envelope_name="FlowRunOutputPayload",
        owner_symbols=("determine_run_outcome", "finalize_run_from_current_results"),
        storage_category=FlowJsonbStorageCategory.RUNTIME_PAYLOAD,
        schema_version_policy=FlowJsonbSchemaVersionPolicy.OWNER_VALIDATED_SHAPE,
        corruption_behavior=FlowJsonbCorruptionBehavior.KEEP_AUDITABLE_FAILURE,
        rationale=(
            "Terminal run output mirrors the final runtime result and is read as "
            "one payload by run-contract projection code."
        ),
    ),
    _owner(
        "flow_runs",
        "error_json",
        owner_module="eneo.flows.flow_run_error",
        envelope_name="FlowRunError",
        owner_symbols=("FlowRunError", "dump_flow_run_error", "parse_flow_run_error"),
        storage_category=FlowJsonbStorageCategory.RUNTIME_PAYLOAD,
        schema_version_policy=FlowJsonbSchemaVersionPolicy.EMBEDDED_SCHEMA_VERSION,
        corruption_behavior=FlowJsonbCorruptionBehavior.KEEP_AUDITABLE_FAILURE,
        rationale=(
            "Terminal error details are a public diagnostic envelope with an "
            "embedded schema version; invalid stored payloads read as one "
            "sanitized typed run error."
        ),
    ),
    _owner(
        "flow_runs",
        "dispatch_last_error",
        owner_module="eneo.flows.flow_run_error",
        envelope_name="FlowRunDispatchError",
        owner_symbols=(
            "FlowRunDispatchError",
            "dump_flow_run_dispatch_error",
            "parse_flow_run_dispatch_error",
        ),
        storage_category=FlowJsonbStorageCategory.RUNTIME_PAYLOAD,
        schema_version_policy=FlowJsonbSchemaVersionPolicy.EMBEDDED_SCHEMA_VERSION,
        corruption_behavior=FlowJsonbCorruptionBehavior.KEEP_AUDITABLE_FAILURE,
        rationale=(
            "The current dispatch epoch stores one bounded, secret-free typed "
            "diagnosis. Invalid persisted payloads read as the canonical "
            "non-retryable invalid-error diagnosis."
        ),
    ),
    _owner(
        "flow_step_results",
        "input_payload_json",
        owner_module="eneo.flows.runtime.step_result_builder",
        envelope_name="FlowStepResultInputPayload",
        owner_symbols=(
            "build_completed_step_input_payload",
            "build_failed_step_result",
        ),
        storage_category=FlowJsonbStorageCategory.RUNTIME_PAYLOAD,
        schema_version_policy="No persisted schema version is currently recorded.",
        corruption_behavior="No dedicated corruption behavior is currently enforced.",
        rationale=(
            "Step-result input is the resolved runtime input snapshot used to "
            "debug what the step saw."
        ),
    ),
    _owner(
        "flow_step_results",
        "output_payload_json",
        owner_module="eneo.flows.runtime.step_result_builder",
        envelope_name="FlowStepResultOutputPayload",
        owner_symbols=("build_completed_step_result",),
        storage_category=FlowJsonbStorageCategory.RUNTIME_PAYLOAD,
        schema_version_policy="No persisted schema version is currently recorded.",
        corruption_behavior="No dedicated corruption behavior is currently enforced.",
        rationale=(
            "Step-result output is mode-specific runtime data projected to API "
            "consumers as one typed result payload."
        ),
    ),
    _owner(
        "flow_step_results",
        "model_parameters_json",
        owner_module="eneo.flows.flow_run_provenance",
        envelope_name="FlowStepModelParameters",
        owner_symbols=("ModelParameterSnapshot", "normalize_model_parameters_payload"),
        storage_category=FlowJsonbStorageCategory.PROVENANCE_EVIDENCE,
        schema_version_policy=FlowJsonbSchemaVersionPolicy.PROVIDER_DEFINED,
        corruption_behavior=FlowJsonbCorruptionBehavior.MARK_EVIDENCE_UNAVAILABLE,
        rationale=(
            "Model parameters are provider-facing provenance, not relational "
            "business state, and may vary by model vendor."
        ),
    ),
    _owner(
        "flow_run_rerun_operations",
        "input_payload_json",
        owner_module="eneo.flows.application.flow_run_rerun_service",
        envelope_name="FlowRunRerunInputEnvelope",
        owner_symbols=("FlowRunRerunService._normalize_rerun_inline_payload",),
        storage_category=FlowJsonbStorageCategory.RERUN_STATE,
        schema_version_policy=FlowJsonbSchemaVersionPolicy.OWNER_VALIDATED_SHAPE,
        corruption_behavior=FlowJsonbCorruptionBehavior.REJECT_BEFORE_WRITE,
        rationale=(
            "Rerun input overrides are captured with the operation so replay and "
            "idempotency can be audited without changing the original run input."
        ),
    ),
    _owner(
        "flow_run_rerun_operations",
        "changed_input_paths",
        owner_module="eneo.flows.domain.flow_run_input_revision",
        envelope_name="FlowRunInputRevision",
        owner_symbols=(
            "build_flow_run_input_revision",
            "changed_input_paths",
            "parse_flow_run_input_revision",
        ),
        storage_category=FlowJsonbStorageCategory.RERUN_STATE,
        schema_version_policy=FlowJsonbSchemaVersionPolicy.OWNER_VALIDATED_SHAPE,
        corruption_behavior=FlowJsonbCorruptionBehavior.MARK_EVIDENCE_UNAVAILABLE,
        rationale=(
            "The changed field paths are a flat list of strings derived from the "
            "two payloads, useful for showing what a rerun altered without "
            "reading either payload."
        ),
    ),
    _owner(
        "flow_run_rerun_operations",
        "prior_input_payload_json",
        owner_module="eneo.flows.domain.flow_run_input_revision",
        envelope_name="FlowRunInputRevision",
        owner_symbols=(
            "build_flow_run_input_revision",
            "parse_flow_run_input_revision",
        ),
        storage_category=FlowJsonbStorageCategory.RERUN_STATE,
        schema_version_policy=FlowJsonbSchemaVersionPolicy.OWNER_VALIDATED_SHAPE,
        corruption_behavior=FlowJsonbCorruptionBehavior.MARK_EVIDENCE_UNAVAILABLE,
        rationale=(
            "The run row keeps only current inputs, so each rerun stores the "
            "payload it replaced; walking reruns in order rebuilds every input "
            "revision. Same data class as the run's own input payload, on a row "
            "that cascade-deletes with the run."
        ),
    ),
    _owner(
        "flow_step_attempt_resolved_inputs",
        "resolved_input_edges_jsonb",
        owner_module="eneo.flows.flow_run_provenance",
        envelope_name="FlowResolvedInputEdges",
        owner_symbols=("FlowResolvedInputEdges", "parse_resolved_input_edges"),
        storage_category=FlowJsonbStorageCategory.PROVENANCE_EVIDENCE,
        schema_version_policy=FlowJsonbSchemaVersionPolicy.EMBEDDED_SCHEMA_VERSION,
        corruption_behavior=FlowJsonbCorruptionBehavior.MARK_EVIDENCE_UNAVAILABLE,
        rationale=(
            "Resolved input edges are one bounded immutable attempt aggregate read "
            "and written whole. A one-to-one evidence row keeps it off the hot attempt "
            "row. It is run-debug evidence and must be deleted at the attempt evidence "
            "retention boundary before a runtime writer is enabled. Per-edge rows are "
            "not needed without independent edge queries, transitions, or retention "
            "lifecycle."
        ),
    ),
    _owner(
        "flow_step_attempts",
        "provenance_json",
        owner_module="eneo.flows.flow_run_provenance",
        envelope_name="FlowStepAttemptProvenance",
        owner_symbols=("FlowAttemptProvenance", "parse_attempt_provenance"),
        storage_category=FlowJsonbStorageCategory.PROVENANCE_EVIDENCE,
        schema_version_policy=FlowJsonbSchemaVersionPolicy.EMBEDDED_SCHEMA_VERSION,
        corruption_behavior=FlowJsonbCorruptionBehavior.MARK_EVIDENCE_UNAVAILABLE,
        rationale=(
            "Attempt provenance v2 excludes facts reconstructed from immutable attempt "
            "payloads, relational result files, provider-call rows, or the published "
            "definition. Its remaining LLM and attempt-start context is diagnostic "
            "until those scalars converge on a typed immutable attempt owner; exact "
            "retrieval evidence and bounded completion, tool-call, admission, and "
            "citation observations have no other reconstruction path."
        ),
    ),
    _owner(
        "flow_step_attempts",
        "input_payload_json",
        owner_module="eneo.flows.runtime.step_result_builder",
        envelope_name="FlowStepAttemptInputPayload",
        owner_symbols=(
            "build_completed_step_input_payload",
            "build_failed_step_result",
        ),
        storage_category=FlowJsonbStorageCategory.RUNTIME_PAYLOAD,
        schema_version_policy=FlowJsonbSchemaVersionPolicy.OWNER_VALIDATED_SHAPE,
        corruption_behavior=FlowJsonbCorruptionBehavior.FAIL_RUN_OR_STEP,
        rationale=(
            "Attempt input is the immutable execution snapshot for a single try "
            "and differs from the current step result during reruns."
        ),
    ),
    _owner(
        "flow_step_attempts",
        "output_payload_json",
        owner_module="eneo.flows.runtime.step_result_builder",
        envelope_name="FlowStepAttemptOutputPayload",
        owner_symbols=("build_completed_step_result",),
        storage_category=FlowJsonbStorageCategory.RUNTIME_PAYLOAD,
        schema_version_policy=FlowJsonbSchemaVersionPolicy.OWNER_VALIDATED_SHAPE,
        corruption_behavior=FlowJsonbCorruptionBehavior.KEEP_AUDITABLE_FAILURE,
        rationale=(
            "Attempt output preserves each try's raw runtime result before the "
            "current step result is updated or superseded."
        ),
    ),
    _owner(
        "flow_run_rerun_invalidated_steps",
        "dependency_sources_json",
        owner_module="eneo.flows.flow_run_rerun_graph",
        envelope_name="RerunInvalidationDependencySources",
        owner_symbols=(
            "RerunInvalidatedStep",
            "RerunInvalidationGraph",
            "build_rerun_invalidation_graph",
        ),
        storage_category=FlowJsonbStorageCategory.RERUN_STATE,
        schema_version_policy=FlowJsonbSchemaVersionPolicy.OWNER_VALIDATED_SHAPE,
        corruption_behavior=FlowJsonbCorruptionBehavior.REJECT_BEFORE_WRITE,
        rationale=(
            "Dependency sources are a bounded string set derived from the rerun "
            "graph and stored with each invalidation row for reviewability."
        ),
    ),
    _owner(
        "flow_run_review_checkpoints",
        "original_payload_json",
        owner_module="eneo.flows.infrastructure.flow_run_review_checkpoint_repo",
        envelope_name="ReviewCheckpointOriginalPayload",
        owner_symbols=(
            "FlowRunReviewCheckpointRepository.create_or_get_review_checkpoint_for_attempt",
            "FlowRunReviewCheckpointRepository.open_review_checkpoint_for_completed_step",
        ),
        storage_category=FlowJsonbStorageCategory.REVIEW_CHECKPOINT,
        schema_version_policy=(
            "schema_version is written as 1 but is not read by a payload parser."
        ),
        corruption_behavior=(
            "There is no dedicated pre-write payload validation at this owner."
        ),
        rationale=(
            "The checkpoint keeps the original reviewed output next to its state "
            "revision so reviewer edits can be compared and audited."
        ),
    ),
    _owner(
        "flow_run_review_checkpoints",
        "current_payload_json",
        owner_module="eneo.flows.infrastructure.flow_run_review_checkpoint_repo",
        envelope_name="ReviewCheckpointCurrentPayload",
        owner_symbols=(
            "FlowRunReviewCheckpointRepository.create_or_get_review_checkpoint_for_attempt",
            "FlowRunReviewCheckpointRepository.edit_review_checkpoint_payload",
        ),
        storage_category=FlowJsonbStorageCategory.REVIEW_CHECKPOINT,
        schema_version_policy=(
            "schema_version is written as 1 but is not read by a payload parser."
        ),
        corruption_behavior=(
            "There is no dedicated pre-write payload validation at this owner."
        ),
        rationale=(
            "Current reviewed output is checkpoint-local mutable state guarded by "
            "checkpoint revision and schema version."
        ),
    ),
    _owner(
        "flow_run_review_checkpoints",
        "output_contract_json",
        owner_module="eneo.flows.infrastructure.flow_run_review_checkpoint_repo",
        envelope_name="ReviewCheckpointOutputContract",
        owner_symbols=(
            "FlowRunReviewCheckpointRepository.create_or_get_review_checkpoint_for_attempt",
            "FlowRunReviewCheckpointRepository.open_review_checkpoint_for_completed_step",
        ),
        storage_category=FlowJsonbStorageCategory.REVIEW_CHECKPOINT,
        schema_version_policy=(
            "schema_version is written as 1 but is not read by a payload parser."
        ),
        corruption_behavior=(
            "There is no dedicated pre-write payload validation at this owner."
        ),
        rationale=(
            "The output contract is snapshotted with the checkpoint so review UI "
            "can validate edits against the published step contract."
        ),
    ),
    _owner(
        "flow_run_review_checkpoints",
        "next_step_ids_json",
        owner_module="eneo.flows.infrastructure.flow_run_review_checkpoint_repo",
        envelope_name="ReviewCheckpointNextStepIds",
        owner_symbols=(
            "FlowRunReviewCheckpointRepository.create_or_get_review_checkpoint_for_attempt",
            "FlowRunReviewCheckpointRepository.open_review_checkpoint_for_completed_step",
        ),
        storage_category=FlowJsonbStorageCategory.REVIEW_CHECKPOINT,
        schema_version_policy=(
            "schema_version is written as 1 but is not read by a payload parser."
        ),
        corruption_behavior=(
            "There is no dedicated pre-write payload validation at this owner."
        ),
        rationale=(
            "Next-step ids are a small resume snapshot from the published graph; "
            "there is no separate row identity to constrain relationally."
        ),
    ),
    _owner(
        "builder_sessions",
        "conversation",
        owner_module="eneo.flows.ai_builder.ai_builder_domain_models",
        envelope_name="ConversationMessage",
        owner_symbols=("ConversationMessage",),
        storage_category=FlowJsonbStorageCategory.BUILDER_SESSION_STATE,
        schema_version_policy=FlowJsonbSchemaVersionPolicy.OWNER_VALIDATED_SHAPE,
        corruption_behavior=FlowJsonbCorruptionBehavior.FAIL_SESSION_LOAD,
        rationale=(
            "Builder conversation history is stored as a JSON array of "
            "ConversationMessage entries; persisted rows fail session loading "
            "when required stable message ids are missing."
        ),
    ),
    _owner(
        "builder_sessions",
        "planning_state_jsonb",
        owner_module="eneo.flows.ai_builder.planning_state",
        envelope_name="PlanningState",
        owner_symbols=("PlanningState",),
        storage_category=FlowJsonbStorageCategory.BUILDER_SESSION_STATE,
        schema_version_policy=FlowJsonbSchemaVersionPolicy.EMBEDDED_SCHEMA_VERSION,
        corruption_behavior=FlowJsonbCorruptionBehavior.FAIL_SESSION_LOAD,
        rationale=(
            "Builder planning state is a full-snapshot PlanningState document "
            "with embedded FCM, planner-contract, and builder schema versions."
        ),
    ),
    _owner(
        "builder_sessions",
        "latest_turn_request_jsonb",
        owner_module="eneo.flows.ai_builder.ai_builder_api_models",
        envelope_name="SendMessageRequest",
        owner_symbols=("SendMessageRequest", "SendMessageRequest.retry_snapshot"),
        storage_category=FlowJsonbStorageCategory.BUILDER_SESSION_STATE,
        schema_version_policy=FlowJsonbSchemaVersionPolicy.OWNER_VALIDATED_SHAPE,
        corruption_behavior=FlowJsonbCorruptionBehavior.FAIL_SESSION_LOAD,
        rationale=(
            "The latest accepted Builder turn retains one bounded strict request "
            "snapshot for same-key replay and explicit outcome-unknown recovery."
        ),
    ),
    _owner(
        "builder_sessions",
        "latest_turn_error_jsonb",
        owner_module="eneo.flows.ai_builder.ai_builder_error_contract",
        envelope_name="AIBuilderPublicError",
        owner_symbols=("AIBuilderPublicError",),
        storage_category=FlowJsonbStorageCategory.BUILDER_SESSION_STATE,
        schema_version_policy=FlowJsonbSchemaVersionPolicy.EMBEDDED_SCHEMA_VERSION,
        corruption_behavior=FlowJsonbCorruptionBehavior.FAIL_SESSION_LOAD,
        rationale=(
            "A committed Builder turn may retain one typed public error for exact "
            "same-key replay; invalid stored errors fail session hydration."
        ),
    ),
    _owner(
        "builder_plans",
        "proposal_json",
        owner_module="eneo.flows.ai_builder.ai_builder_domain_models",
        envelope_name="FlowBuilderProposal",
        owner_symbols=(
            "FlowBuilderProposal",
            "FlowBuilderProposal.from_persisted_json",
            "FlowBuilderProposal.storage_json",
        ),
        storage_category=FlowJsonbStorageCategory.IMMUTABLE_SNAPSHOT,
        schema_version_policy=FlowJsonbSchemaVersionPolicy.EMBEDDED_SCHEMA_VERSION,
        corruption_behavior=FlowJsonbCorruptionBehavior.FAIL_PLAN_LOAD,
        rationale=(
            "Builder plans persist one current-version-only immutable proposal "
            "snapshot. Writes and reads validate the typed envelope and 1 MiB "
            "payload cap; invalid stored proposals fail plan hydration, while "
            "spec_hash rejects silent row drift."
        ),
    ),
)

FLOW_JSONB_COLUMN_OWNERS = build_flow_jsonb_owner_map(FLOW_JSONB_COLUMN_OWNER_ENTRIES)
