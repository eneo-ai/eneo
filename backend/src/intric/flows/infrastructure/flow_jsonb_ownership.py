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
    DEFERRED_INVENTORY = "deferred_inventory"


class FlowJsonbSchemaVersionPolicy(StrEnum):
    EMBEDDED_SCHEMA_VERSION = "embedded_schema_version"
    TABLE_SCHEMA_VERSION = "table_schema_version"
    CHECKSUMMED_SNAPSHOT = "checksummed_snapshot"
    OWNER_VALIDATED_SHAPE = "owner_validated_shape"
    PROVIDER_DEFINED = "provider_defined"
    DEFERRED_INVENTORY = "deferred_inventory"


class FlowJsonbCorruptionBehavior(StrEnum):
    REJECT_BEFORE_WRITE = "reject_before_write"
    FAIL_RUN_OR_STEP = "fail_run_or_step"
    KEEP_AUDITABLE_FAILURE = "keep_auditable_failure"
    MARK_EVIDENCE_UNAVAILABLE = "mark_evidence_unavailable"
    NORMALIZE_TO_EMPTY = "normalize_to_empty"
    DEFERRED_INVENTORY = "deferred_inventory"


@dataclass(frozen=True, slots=True)
class FlowJsonbColumnOwner:
    table_name: str
    column_name: str
    owner_module: str
    envelope_name: str
    storage_category: FlowJsonbStorageCategory
    schema_version_policy: FlowJsonbSchemaVersionPolicy
    corruption_behavior: FlowJsonbCorruptionBehavior
    relational_candidate: bool
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
    storage_category: FlowJsonbStorageCategory,
    schema_version_policy: FlowJsonbSchemaVersionPolicy,
    corruption_behavior: FlowJsonbCorruptionBehavior,
    rationale: str,
    relational_candidate: bool = False,
) -> FlowJsonbColumnOwner:
    return FlowJsonbColumnOwner(
        table_name=table_name,
        column_name=column_name,
        owner_module=owner_module,
        envelope_name=envelope_name,
        storage_category=storage_category,
        schema_version_policy=schema_version_policy,
        corruption_behavior=corruption_behavior,
        relational_candidate=relational_candidate,
        rationale=rationale,
    )


FLOW_JSONB_COLUMN_OWNER_ENTRIES: tuple[FlowJsonbColumnOwner, ...] = (
    _owner(
        "flows",
        "metadata_json",
        owner_module="intric.flows.flow_metadata",
        envelope_name="FlowMetadata",
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
        owner_module="intric.flows.runtime.step_definition_parser",
        envelope_name="StepInputContract",
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
        owner_module="intric.flows.runtime.step_definition_parser",
        envelope_name="StepOutputContract",
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
        owner_module="intric.flows.runtime.step_definition_parser",
        envelope_name="StepInputBindings",
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
        owner_module="intric.flows.runtime.step_definition_parser",
        envelope_name="StepInputConfig",
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
        owner_module="intric.flows.runtime.step_definition_parser",
        envelope_name="StepOutputConfig",
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
        owner_module="intric.flows.flow_review_policy",
        envelope_name="FlowReviewPolicy",
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
        owner_module="intric.flows.published_definition",
        envelope_name="PublishedFlowDefinition",
        storage_category=FlowJsonbStorageCategory.IMMUTABLE_SNAPSHOT,
        schema_version_policy=FlowJsonbSchemaVersionPolicy.CHECKSUMMED_SNAPSHOT,
        corruption_behavior=FlowJsonbCorruptionBehavior.REJECT_BEFORE_WRITE,
        rationale=(
            "Published definitions are immutable, checksummed snapshots of the "
            "runtime contract and should be loaded as one versioned document."
        ),
    ),
    _owner(
        "flow_template_assets",
        "placeholders",
        owner_module="intric.flows.flow_template_asset_service",
        envelope_name="TemplateAssetPlaceholders",
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
        owner_module="intric.flow_packages.domain.flow_package_import_plan",
        envelope_name="FlowPackageImportPlan",
        storage_category=FlowJsonbStorageCategory.IMPORT_STATE,
        schema_version_policy=FlowJsonbSchemaVersionPolicy.EMBEDDED_SCHEMA_VERSION,
        corruption_behavior=FlowJsonbCorruptionBehavior.REJECT_BEFORE_WRITE,
        rationale=(
            "Import plans are portable package decisions with their own schema "
            "version and are applied atomically, not queried field-by-field."
        ),
    ),
    _owner(
        "flow_package_imports",
        "selected_mappings_json",
        owner_module="intric.flow_packages.domain.flow_package_import_record",
        envelope_name="FlowPackageSelectedMappings",
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
        owner_module="intric.flow_packages.domain.flow_package_import_record",
        envelope_name="FlowPackageImportFailure",
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
        owner_module="intric.flows.flow_run_input_envelope",
        envelope_name="FlowRunInputEnvelope",
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
        owner_module="intric.flows.runtime.run_outcome",
        envelope_name="FlowRunOutputPayload",
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
        owner_module="intric.flows.flow_run_error",
        envelope_name="FlowRunError",
        storage_category=FlowJsonbStorageCategory.RUNTIME_PAYLOAD,
        schema_version_policy=FlowJsonbSchemaVersionPolicy.EMBEDDED_SCHEMA_VERSION,
        corruption_behavior=FlowJsonbCorruptionBehavior.KEEP_AUDITABLE_FAILURE,
        rationale=(
            "Terminal error details are a public diagnostic envelope with an "
            "embedded schema version and string-safe parser for old rows."
        ),
    ),
    _owner(
        "flow_step_results",
        "input_payload_json",
        owner_module="intric.flows.runtime.step_result_builder",
        envelope_name="FlowStepResultInputPayload",
        storage_category=FlowJsonbStorageCategory.RUNTIME_PAYLOAD,
        schema_version_policy=FlowJsonbSchemaVersionPolicy.OWNER_VALIDATED_SHAPE,
        corruption_behavior=FlowJsonbCorruptionBehavior.FAIL_RUN_OR_STEP,
        rationale=(
            "Step-result input is the resolved runtime input snapshot used to "
            "debug what the step saw."
        ),
    ),
    _owner(
        "flow_step_results",
        "output_payload_json",
        owner_module="intric.flows.runtime.step_result_builder",
        envelope_name="FlowStepResultOutputPayload",
        storage_category=FlowJsonbStorageCategory.RUNTIME_PAYLOAD,
        schema_version_policy=FlowJsonbSchemaVersionPolicy.OWNER_VALIDATED_SHAPE,
        corruption_behavior=FlowJsonbCorruptionBehavior.KEEP_AUDITABLE_FAILURE,
        rationale=(
            "Step-result output is mode-specific runtime data projected to API "
            "consumers as one typed result payload."
        ),
    ),
    _owner(
        "flow_step_results",
        "model_parameters_json",
        owner_module="intric.flows.flow_run_provenance",
        envelope_name="FlowStepModelParameters",
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
        owner_module="intric.flows.application.flow_run_rerun_service",
        envelope_name="FlowRunRerunInputEnvelope",
        storage_category=FlowJsonbStorageCategory.RERUN_STATE,
        schema_version_policy=FlowJsonbSchemaVersionPolicy.OWNER_VALIDATED_SHAPE,
        corruption_behavior=FlowJsonbCorruptionBehavior.REJECT_BEFORE_WRITE,
        rationale=(
            "Rerun input overrides are captured with the operation so replay and "
            "idempotency can be audited without changing the original run input."
        ),
    ),
    _owner(
        "flow_step_attempts",
        "provenance_json",
        owner_module="intric.flows.flow_run_provenance",
        envelope_name="FlowStepAttemptProvenance",
        storage_category=FlowJsonbStorageCategory.PROVENANCE_EVIDENCE,
        schema_version_policy=FlowJsonbSchemaVersionPolicy.EMBEDDED_SCHEMA_VERSION,
        corruption_behavior=FlowJsonbCorruptionBehavior.MARK_EVIDENCE_UNAVAILABLE,
        rationale=(
            "Attempt provenance records provider, retrieval, and evidence context "
            "whose shape is useful as one diagnostic document."
        ),
    ),
    _owner(
        "flow_step_attempts",
        "input_payload_json",
        owner_module="intric.flows.runtime.step_result_builder",
        envelope_name="FlowStepAttemptInputPayload",
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
        owner_module="intric.flows.runtime.step_result_builder",
        envelope_name="FlowStepAttemptOutputPayload",
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
        owner_module="intric.flows.flow_run_rerun_graph",
        envelope_name="RerunInvalidationDependencySources",
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
        owner_module="intric.flows.application.flow_run_review_checkpoint_service",
        envelope_name="ReviewCheckpointOriginalPayload",
        storage_category=FlowJsonbStorageCategory.REVIEW_CHECKPOINT,
        schema_version_policy=FlowJsonbSchemaVersionPolicy.TABLE_SCHEMA_VERSION,
        corruption_behavior=FlowJsonbCorruptionBehavior.REJECT_BEFORE_WRITE,
        rationale=(
            "The checkpoint keeps the original reviewed output next to its state "
            "revision so reviewer edits can be compared and audited."
        ),
    ),
    _owner(
        "flow_run_review_checkpoints",
        "current_payload_json",
        owner_module="intric.flows.application.flow_run_review_checkpoint_service",
        envelope_name="ReviewCheckpointCurrentPayload",
        storage_category=FlowJsonbStorageCategory.REVIEW_CHECKPOINT,
        schema_version_policy=FlowJsonbSchemaVersionPolicy.TABLE_SCHEMA_VERSION,
        corruption_behavior=FlowJsonbCorruptionBehavior.REJECT_BEFORE_WRITE,
        rationale=(
            "Current reviewed output is checkpoint-local mutable state guarded by "
            "checkpoint revision and schema version."
        ),
    ),
    _owner(
        "flow_run_review_checkpoints",
        "output_contract_json",
        owner_module="intric.flows.application.flow_run_review_checkpoint_service",
        envelope_name="ReviewCheckpointOutputContract",
        storage_category=FlowJsonbStorageCategory.REVIEW_CHECKPOINT,
        schema_version_policy=FlowJsonbSchemaVersionPolicy.TABLE_SCHEMA_VERSION,
        corruption_behavior=FlowJsonbCorruptionBehavior.REJECT_BEFORE_WRITE,
        rationale=(
            "The output contract is snapshotted with the checkpoint so review UI "
            "can validate edits against the published step contract."
        ),
    ),
    _owner(
        "flow_run_review_checkpoints",
        "next_step_ids_json",
        owner_module="intric.flows.infrastructure.flow_run_review_checkpoint_repo",
        envelope_name="ReviewCheckpointNextStepIds",
        storage_category=FlowJsonbStorageCategory.REVIEW_CHECKPOINT,
        schema_version_policy=FlowJsonbSchemaVersionPolicy.TABLE_SCHEMA_VERSION,
        corruption_behavior=FlowJsonbCorruptionBehavior.REJECT_BEFORE_WRITE,
        rationale=(
            "Next-step ids are a small resume snapshot from the published graph; "
            "there is no separate row identity to constrain relationally."
        ),
    ),
    _owner(
        "module_registry",
        "metadata_json",
        owner_module="intric.database.tables.flow_tables",
        envelope_name="ModuleRegistryMetadata",
        storage_category=FlowJsonbStorageCategory.DEFERRED_INVENTORY,
        schema_version_policy=FlowJsonbSchemaVersionPolicy.DEFERRED_INVENTORY,
        corruption_behavior=FlowJsonbCorruptionBehavior.DEFERRED_INVENTORY,
        rationale=(
            "This adjacent table-module JSON column is registered so the metadata "
            "guard has no hidden exclusions; a platform inventory should own it."
        ),
    ),
    _owner(
        "builder_sessions",
        "conversation",
        owner_module="intric.flows.ai_builder.ai_builder_repo",
        envelope_name="AiBuilderConversation",
        storage_category=FlowJsonbStorageCategory.DEFERRED_INVENTORY,
        schema_version_policy=FlowJsonbSchemaVersionPolicy.DEFERRED_INVENTORY,
        corruption_behavior=FlowJsonbCorruptionBehavior.DEFERRED_INVENTORY,
        rationale=(
            "Flow AI Builder history is adjacent in flow_tables.py but outside "
            "this Flow-proper slice; registering it prevents hidden exclusions."
        ),
    ),
    _owner(
        "builder_sessions",
        "planning_state_jsonb",
        owner_module="intric.flows.ai_builder.ai_builder_repo",
        envelope_name="AiBuilderPlanningState",
        storage_category=FlowJsonbStorageCategory.DEFERRED_INVENTORY,
        schema_version_policy=FlowJsonbSchemaVersionPolicy.DEFERRED_INVENTORY,
        corruption_behavior=FlowJsonbCorruptionBehavior.DEFERRED_INVENTORY,
        rationale=(
            "Planning state already has dedicated AI Builder discipline, but it "
            "must stay visible to the table-module JSONB inventory."
        ),
    ),
    _owner(
        "builder_plans",
        "proposal_json",
        owner_module="intric.flows.ai_builder.ai_builder_repo",
        envelope_name="FlowBuilderProposal",
        storage_category=FlowJsonbStorageCategory.IMMUTABLE_SNAPSHOT,
        schema_version_policy=FlowJsonbSchemaVersionPolicy.OWNER_VALIDATED_SHAPE,
        corruption_behavior=FlowJsonbCorruptionBehavior.REJECT_BEFORE_WRITE,
        rationale=(
            "Builder plans persist one immutable proposal snapshot validated "
            "through FlowBuilderProposal; spec_hash rejects silent row drift."
        ),
    ),
)

FLOW_JSONB_COLUMN_OWNERS = build_flow_jsonb_owner_map(FLOW_JSONB_COLUMN_OWNER_ENTRIES)
