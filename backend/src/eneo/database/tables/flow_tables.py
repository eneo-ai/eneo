from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from eneo.data_retention.constants import MAX_RETENTION_DAYS, MIN_RETENTION_DAYS
from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.base_class import (
    BaseCrossReference,
    BasePublic,
)
from eneo.database.tables.files_table import Files
from eneo.database.tables.job_table import Jobs
from eneo.database.tables.spaces_table import Spaces
from eneo.database.tables.tenant_table import Tenants
from eneo.database.tables.users_table import Users
from eneo.flow_packages.domain.flow_package_import_record import (
    FlowPackageImportSource,
    FlowPackageImportStatus,
)
from eneo.flows.enums import (
    ACTIVE_FLOW_RUN_REVIEW_CHECKPOINT_STATES,
    FLOW_INPUT_SOURCE_VALUES,
    FLOW_INPUT_TYPE_VALUES,
    FLOW_OUTPUT_MODE_VALUES,
    FLOW_OUTPUT_TYPE_VALUES,
    RECONCILABLE_REVIEW_CHECKPOINT_STATES,
    TERMINAL_FLOW_RUN_STATUS_VALUES,
    FlowRunLifecycleSource,
    FlowRunRerunInvalidationRole,
    FlowRunRerunOperationStatus,
    FlowRunReviewCheckpointState,
    FlowRunStatus,
    FlowStepAttemptStatus,
    FlowStepResultStatus,
    FlowTemplateAssetStatus,
)
from eneo.flows.flow_resource_bindings import (
    FLOW_RESOURCE_BINDING_SOURCE_VALUES,
    RESOURCE_SLOT_LOCAL_KIND_PAIRS,
    RESOURCE_SLOT_PATTERN,
    UUID_SHAPED_RESOURCE_REF_PATTERN,
    LocalResourceKind,
    ResourceSlotKind,
)
from eneo.flows.flow_review_policy import FlowStepReviewMode

FLOW_STEP_INPUT_SOURCE_VALUES = FLOW_INPUT_SOURCE_VALUES
FLOW_STEP_INPUT_TYPE_VALUES = FLOW_INPUT_TYPE_VALUES
FLOW_STEP_OUTPUT_MODE_VALUES = FLOW_OUTPUT_MODE_VALUES
FLOW_STEP_OUTPUT_TYPE_VALUES = FLOW_OUTPUT_TYPE_VALUES
FLOW_RUN_STATUS_VALUES = tuple(item.value for item in FlowRunStatus)
FLOW_RUN_RERUN_OPERATION_STATUS_VALUES = tuple(
    item.value for item in FlowRunRerunOperationStatus
)
FLOW_RUN_RERUN_INVALIDATION_ROLE_VALUES = tuple(
    item.value for item in FlowRunRerunInvalidationRole
)
FLOW_RUN_LIFECYCLE_SOURCE_VALUES = tuple(item.value for item in FlowRunLifecycleSource)
FLOW_DATA_RETENTION_DAYS_RANGE_CHECK = (
    "data_retention_days IS NULL OR "
    f"(data_retention_days >= {MIN_RETENTION_DAYS} "
    f"AND data_retention_days <= {MAX_RETENTION_DAYS})"
)
FLOW_RUN_REVIEW_CHECKPOINT_STATE_VALUES = tuple(
    item.value for item in FlowRunReviewCheckpointState
)
FLOW_STEP_REVIEW_MODE_VALUES = tuple(item.value for item in FlowStepReviewMode)
FLOW_RUN_ACTIVE_REVIEW_CHECKPOINT_STATE_VALUES = tuple(
    state.value
    for state in FlowRunReviewCheckpointState
    if state in ACTIVE_FLOW_RUN_REVIEW_CHECKPOINT_STATES
)
FLOW_RUN_RECONCILABLE_REVIEW_CHECKPOINT_STATE_VALUES = tuple(
    state.value
    for state in FlowRunReviewCheckpointState
    if state in RECONCILABLE_REVIEW_CHECKPOINT_STATES
)
FLOW_RUN_AUDIT_TARGET_STATUS_VALUES = tuple(
    dict.fromkeys(
        (
            FlowRunStatus.COMPLETED.value,
            FlowRunStatus.FAILED.value,
            FlowRunStatus.CANCELLED.value,
            *FLOW_RUN_REVIEW_CHECKPOINT_STATE_VALUES,
        )
    )
)


class FlowOutboxDeliveryStatus(str, Enum):
    PENDING = "pending"
    DELIVERED = "delivered"
    DEAD_LETTERED = "dead_lettered"


# Keep table-specific tuple names because each SQL CHECK constraint belongs to
# one table; the enum owns the shared vocabulary.
FLOW_RUN_AUDIT_OUTBOX_DELIVERY_STATUS_VALUES = tuple(
    item.value for item in FlowOutboxDeliveryStatus
)
FLOW_RUN_WEBHOOK_DELIVERY_STATUS_VALUES = tuple(
    item.value for item in FlowOutboxDeliveryStatus
)
FLOW_STEP_RESULT_STATUS_VALUES = tuple(item.value for item in FlowStepResultStatus)
FLOW_STEP_ATTEMPT_STATUS_VALUES = tuple(item.value for item in FlowStepAttemptStatus)
FLOW_RUN_STEP_RESULT_FILE_SOURCE_VALUES = ("generated_output", "declared_artifact")
MODULE_HEALTH_STATUS_VALUES = ("healthy", "unhealthy", "unknown")
MODULE_COMPAT_STATUS_VALUES = ("compatible", "incompatible", "unknown")
FLOW_TEMPLATE_ASSET_STATUS_VALUES = tuple(
    item.value for item in FlowTemplateAssetStatus
)
FLOW_RESOURCE_SLOT_KIND_VALUES = tuple(item.value for item in ResourceSlotKind)
FLOW_RESOURCE_LOCAL_RESOURCE_KIND_VALUES = tuple(
    item.value for item in LocalResourceKind
)
FLOW_RESOURCE_SLOT_LOCAL_KIND_PAIR_VALUES = RESOURCE_SLOT_LOCAL_KIND_PAIRS
FLOW_PACKAGE_IMPORT_SOURCE_VALUES = tuple(
    item.value for item in FlowPackageImportSource
)
FLOW_PACKAGE_IMPORT_STATUS_VALUES = tuple(
    item.value for item in FlowPackageImportStatus
)


def _check_values(values: tuple[str, ...]) -> str:
    return ",".join(f"'{value}'" for value in values)


def _index_values(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


FLOW_RUN_TERMINAL_RETENTION_ANCHOR_INDEX_PREDICATE = (
    f"status IN ({_index_values(TERMINAL_FLOW_RUN_STATUS_VALUES)})"
)


def _check_value_pairs(values: tuple[tuple[str, str], ...]) -> str:
    return ",".join(f"('{left}','{right}')" for left, right in values)


class Flows(BasePublic):
    """Stores mutable Flow drafts and publish pointers. Writer: FlowRepository. Purpose: keep authoring state separate from immutable runtime versions."""

    name: Mapped[str] = mapped_column(nullable=False)
    description: Mapped[Optional[str]] = mapped_column(nullable=True)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    space_id: Mapped[UUID] = mapped_column(
        ForeignKey(Spaces.id, ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_by_user_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Users.id, ondelete="SET NULL"),
        nullable=True,
    )
    owner_user_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Users.id, ondelete="SET NULL"),
        nullable=True,
    )
    published_version: Mapped[Optional[int]] = mapped_column(nullable=True)
    metadata_json: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )
    data_retention_days: Mapped[Optional[int]] = mapped_column(nullable=True)
    draft_revision: Mapped[int] = mapped_column(nullable=False, server_default="0")
    deleted_at: Mapped[Optional[datetime]] = mapped_column(sa.DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            FLOW_DATA_RETENTION_DAYS_RANGE_CHECK,
            name="ck_flows_data_retention_days_range",
        ),
        UniqueConstraint("id", "tenant_id", name="uq_flows_id_tenant_id"),
        UniqueConstraint(
            "id",
            "tenant_id",
            "space_id",
            name="uq_flows_id_tenant_id_space_id",
        ),
        ForeignKeyConstraint(
            ["id", "published_version"],
            ["flow_versions.flow_id", "flow_versions.version"],
            ondelete="NO ACTION",
            onupdate="NO ACTION",
            name="fk_flows_published_version",
        ),
        # W13: active flow names are unique per space.
        Index(
            "uq_flows_space_id_name_active",
            "space_id",
            "name",
            unique=True,
            postgresql_where=sa.text("deleted_at IS NULL"),
        ),
        Index("ix_flows_space_deleted", "space_id", "deleted_at"),
    )


class FlowSteps(BasePublic):
    """Stores ordered draft step configuration. Writer: FlowRepository. Purpose: define the editable step graph before publish freezes a version."""

    flow_id: Mapped[UUID] = mapped_column(
        ForeignKey(Flows.id, ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    assistant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Assistants.id, ondelete="RESTRICT"),
        nullable=False,
    )
    step_order: Mapped[int] = mapped_column(nullable=False)
    timeout_seconds: Mapped[Optional[int]] = mapped_column(nullable=True)
    user_description: Mapped[Optional[str]] = mapped_column(nullable=True)
    input_source: Mapped[str] = mapped_column(
        sa.String(64),
        nullable=False,
        server_default="flow_input",
    )
    input_type: Mapped[str] = mapped_column(
        sa.String(32),
        nullable=False,
        server_default="any",
    )
    input_contract: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )
    output_mode: Mapped[str] = mapped_column(
        sa.String(32),
        nullable=False,
        server_default="pass_through",
    )
    output_type: Mapped[str] = mapped_column(
        sa.String(32),
        nullable=False,
        server_default="text",
    )
    output_contract: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )
    input_bindings: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )
    output_classification_override: Mapped[Optional[int]] = mapped_column(nullable=True)
    input_config: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    output_config: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )
    review_policy: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )

    __table_args__ = (
        UniqueConstraint("flow_id", "step_order", name="uq_flow_steps_flow_step_order"),
        UniqueConstraint("flow_id", "id", name="uq_flow_steps_flow_id_id"),
        UniqueConstraint("id", "tenant_id", name="uq_flow_steps_id_tenant_id"),
        CheckConstraint(
            "step_order >= 1",
            name="ck_flow_steps_step_order_positive",
        ),
        CheckConstraint(
            f"input_source IN ({_check_values(FLOW_STEP_INPUT_SOURCE_VALUES)})",
            name="ck_flow_steps_input_source",
        ),
        CheckConstraint(
            f"input_type IN ({_check_values(FLOW_STEP_INPUT_TYPE_VALUES)})",
            name="ck_flow_steps_input_type",
        ),
        CheckConstraint(
            f"output_mode IN ({_check_values(FLOW_STEP_OUTPUT_MODE_VALUES)})",
            name="ck_flow_steps_output_mode",
        ),
        CheckConstraint(
            f"output_type IN ({_check_values(FLOW_STEP_OUTPUT_TYPE_VALUES)})",
            name="ck_flow_steps_output_type",
        ),
        CheckConstraint(
            "NOT (input_type = 'text' AND output_mode = 'pass_through' "
            "AND output_type IN ('pdf','docx'))",
            name="ck_flow_steps_no_text_document_pass_through",
        ),
        CheckConstraint(
            "timeout_seconds IS NULL OR timeout_seconds > 0",
            name="ck_flow_steps_timeout_seconds_positive",
        ),
        ForeignKeyConstraint(
            ["flow_id", "tenant_id"],
            ["flows.id", "flows.tenant_id"],
            ondelete="CASCADE",
            name="fk_flow_steps_flow_tenant",
        ),
        Index("ix_flow_steps_assistant_id", "assistant_id"),
    )


class FlowStepDependencies(BaseCrossReference):
    """Stores explicit draft step dependency edges. Writer: FlowRepository. Purpose: keep authored graph constraints queryable and tenant-scoped."""

    flow_id: Mapped[UUID] = mapped_column(
        ForeignKey(Flows.id, ondelete="CASCADE"),
        primary_key=True,
    )
    parent_step_id: Mapped[UUID] = mapped_column(
        ForeignKey(FlowSteps.id, ondelete="CASCADE"),
        primary_key=True,
    )
    child_step_id: Mapped[UUID] = mapped_column(
        ForeignKey(FlowSteps.id, ondelete="CASCADE"),
        primary_key=True,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    __table_args__ = (
        CheckConstraint(
            "parent_step_id <> child_step_id",
            name="ck_flow_step_dependencies_no_self_ref",
        ),
        ForeignKeyConstraint(
            ["flow_id", "parent_step_id"],
            ["flow_steps.flow_id", "flow_steps.id"],
            ondelete="CASCADE",
            name="fk_flow_step_deps_parent_same_flow",
        ),
        ForeignKeyConstraint(
            ["flow_id", "child_step_id"],
            ["flow_steps.flow_id", "flow_steps.id"],
            ondelete="CASCADE",
            name="fk_flow_step_deps_child_same_flow",
        ),
        ForeignKeyConstraint(
            ["flow_id", "tenant_id"],
            ["flows.id", "flows.tenant_id"],
            ondelete="CASCADE",
            name="fk_flow_step_deps_flow_tenant",
        ),
    )


class FlowVersions(BaseCrossReference):
    """Stores immutable published Flow definitions. Writer: FlowRepository. Purpose: provide checksummed runtime snapshots for every run."""

    flow_id: Mapped[UUID] = mapped_column(
        ForeignKey(Flows.id, ondelete="CASCADE"),
        primary_key=True,
    )
    version: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    definition_checksum: Mapped[str] = mapped_column(nullable=False)
    definition_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["flow_id", "tenant_id"],
            ["flows.id", "flows.tenant_id"],
            ondelete="CASCADE",
            name="fk_flow_versions_flow_tenant",
        ),
        UniqueConstraint("flow_id", "version", name="uq_flow_versions_flow_version"),
    )


class FlowTemplateAssets(BasePublic):
    """Stores DOCX template assets for a Flow. Writer: FlowTemplateAssetRepository. Purpose: bind uploaded template files and placeholder indexes to authoring."""

    flow_id: Mapped[UUID] = mapped_column(
        ForeignKey(Flows.id, ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    space_id: Mapped[UUID] = mapped_column(
        ForeignKey(Spaces.id, ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    file_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    name: Mapped[str] = mapped_column(nullable=False)
    checksum: Mapped[str] = mapped_column(nullable=False)
    mimetype: Mapped[Optional[str]] = mapped_column(nullable=True)
    placeholders: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    created_by_user_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Users.id, ondelete="SET NULL"),
        nullable=True,
    )
    updated_by_user_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Users.id, ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        sa.String(32),
        nullable=False,
        server_default="ready",
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(sa.DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint(
            "id", "tenant_id", name="uq_flow_template_assets_id_tenant_id"
        ),
        ForeignKeyConstraint(
            ["flow_id", "tenant_id"],
            ["flows.id", "flows.tenant_id"],
            ondelete="CASCADE",
            name="fk_flow_template_assets_flow_tenant",
        ),
        ForeignKeyConstraint(
            ["file_id", "tenant_id"],
            ["files.id", "files.tenant_id"],
            ondelete="RESTRICT",
            name="fk_flow_template_assets_file_tenant",
        ),
        CheckConstraint(
            f"status IN ({_check_values(FLOW_TEMPLATE_ASSET_STATUS_VALUES)})",
            name="ck_flow_template_assets_status",
        ),
        Index(
            "ix_flow_template_assets_flow_active",
            "flow_id",
            "updated_at",
            postgresql_where=sa.text("deleted_at IS NULL"),
        ),
    )


class FlowResourceBindings(BasePublic):
    """Stores local resource bindings for a Flow. Writer: FlowRepository. Purpose: keep tenant-local resource ids outside portable flow packages."""

    flow_id: Mapped[UUID] = mapped_column(
        ForeignKey(Flows.id, ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    space_id: Mapped[UUID] = mapped_column(
        ForeignKey(Spaces.id, ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    slot_kind: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    slot: Mapped[str] = mapped_column(sa.String(96), nullable=False)
    slot_label: Mapped[str] = mapped_column(sa.String(160), nullable=False)
    local_resource_kind: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    local_resource_id: Mapped[UUID] = mapped_column(nullable=False)
    source: Mapped[str] = mapped_column(sa.String(32), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "flow_id",
            "slot_kind",
            "slot",
            name="uq_flow_resource_bindings_flow_slot",
        ),
        ForeignKeyConstraint(
            ["flow_id", "tenant_id"],
            ["flows.id", "flows.tenant_id"],
            ondelete="CASCADE",
            name="fk_flow_resource_bindings_flow_tenant",
        ),
        CheckConstraint(
            f"slot_kind IN ({_check_values(FLOW_RESOURCE_SLOT_KIND_VALUES)})",
            name="ck_flow_resource_bindings_slot_kind",
        ),
        CheckConstraint(
            f"slot ~ '{RESOURCE_SLOT_PATTERN}'",
            name="ck_flow_resource_bindings_slot_format",
        ),
        CheckConstraint(
            f"slot !~* '{UUID_SHAPED_RESOURCE_REF_PATTERN}'",
            name="ck_flow_resource_bindings_slot_not_uuid",
        ),
        CheckConstraint(
            "length(btrim(slot_label)) > 0",
            name="ck_flow_resource_bindings_slot_label_not_empty",
        ),
        CheckConstraint(
            "local_resource_kind IN "
            f"({_check_values(FLOW_RESOURCE_LOCAL_RESOURCE_KIND_VALUES)})",
            name="ck_flow_resource_bindings_local_resource_kind",
        ),
        CheckConstraint(
            "(slot_kind, local_resource_kind) IN "
            f"({_check_value_pairs(FLOW_RESOURCE_SLOT_LOCAL_KIND_PAIR_VALUES)})",
            name="ck_flow_resource_bindings_slot_local_kind_pair",
        ),
        CheckConstraint(
            f"source IN ({_check_values(FLOW_RESOURCE_BINDING_SOURCE_VALUES)})",
            name="ck_flow_resource_bindings_source",
        ),
        Index(
            "ix_flow_resource_bindings_local_target",
            "local_resource_kind",
            "local_resource_id",
        ),
        Index("ix_flow_resource_bindings_tenant_flow", "tenant_id", "flow_id"),
    )


class FlowRuntimeUploadedFiles(BaseCrossReference):
    """Stores reusable runtime upload files. Writer: FlowRuntimeUploadRepository. Purpose: bind pre-run uploads to a Flow, step, tenant, and principal."""

    file_id: Mapped[UUID] = mapped_column(primary_key=True)
    flow_id: Mapped[UUID] = mapped_column(
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    uploaded_for_step_id: Mapped[UUID] = mapped_column(
        nullable=False,
        comment=(
            "Published runtime step id that accepted the upload; provenance "
            "metadata, not a draft flow_steps foreign key."
        ),
    )
    owner_type: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    owner_user_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Users.id, ondelete="RESTRICT"),
        nullable=True,
    )
    owner_service_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("service_principals.id", ondelete="RESTRICT"),
        nullable=True,
    )

    __table_args__ = (
        # The step-input FK targets the full runtime provenance tuple; file_id
        # remains the logical one-row key for a stored runtime upload.
        UniqueConstraint(
            "file_id",
            "flow_id",
            "tenant_id",
            name="uq_flow_runtime_uploaded_files_file_flow_tenant",
        ),
        ForeignKeyConstraint(
            ["flow_id", "tenant_id"],
            ["flows.id", "flows.tenant_id"],
            ondelete="CASCADE",
            name="fk_flow_runtime_uploaded_files_flow_tenant",
        ),
        ForeignKeyConstraint(
            ["file_id", "tenant_id"],
            ["files.id", "files.tenant_id"],
            ondelete="CASCADE",
            name="fk_flow_runtime_uploaded_files_file_tenant",
        ),
        CheckConstraint(
            "owner_type IN ('user','service_key')",
            name="ck_flow_runtime_uploaded_files_owner_type",
        ),
        CheckConstraint(
            "("
            "owner_type = 'user' "
            "AND owner_user_id IS NOT NULL "
            "AND owner_service_id IS NULL"
            ") OR ("
            "owner_type = 'service_key' "
            "AND owner_user_id IS NULL "
            "AND owner_service_id IS NOT NULL"
            ")",
            name="ck_flow_runtime_uploaded_files_owner_identity",
        ),
        Index(
            "ix_flow_runtime_uploaded_files_user_owner",
            "tenant_id",
            "flow_id",
            "owner_user_id",
            "created_at",
            postgresql_where=sa.text("owner_type = 'user'"),
        ),
        Index(
            "ix_flow_runtime_uploaded_files_service_owner",
            "tenant_id",
            "flow_id",
            "owner_service_id",
            "created_at",
            postgresql_where=sa.text("owner_type = 'service_key'"),
        ),
    )


class FlowPackageImports(BasePublic):
    """Stores Flow package import outcomes. Writer: FlowPackageImportRepository. Purpose: retain operational results only while their owning Flow or space exists."""

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    space_id: Mapped[UUID] = mapped_column(
        ForeignKey(Spaces.id, ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    flow_id: Mapped[Optional[UUID]] = mapped_column(
        nullable=True,
        index=True,
    )
    created_by_user_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Users.id, ondelete="SET NULL"),
        nullable=True,
    )
    package_id: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    package_version: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    content_checksum: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    source: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    status: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    import_plan_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    selected_mappings_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
    )
    failure_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        CheckConstraint(
            f"source IN ({_check_values(FLOW_PACKAGE_IMPORT_SOURCE_VALUES)})",
            name="ck_flow_package_imports_source",
        ),
        CheckConstraint(
            f"status IN ({_check_values(FLOW_PACKAGE_IMPORT_STATUS_VALUES)})",
            name="ck_flow_package_imports_status",
        ),
        CheckConstraint(
            "content_checksum ~ '^[0-9a-f]{64}$'",
            name="ck_flow_package_imports_content_checksum",
        ),
        CheckConstraint(
            "("
            "status = 'draft_created' AND flow_id IS NOT NULL AND failure_json IS NULL"
            ") OR ("
            "status = 'failed' AND flow_id IS NULL AND failure_json IS NOT NULL"
            ")",
            name="ck_flow_package_imports_terminal_shape",
        ),
        ForeignKeyConstraint(
            ["flow_id", "tenant_id", "space_id"],
            ["flows.id", "flows.tenant_id", "flows.space_id"],
            ondelete="CASCADE",
            onupdate="NO ACTION",
            name="fk_flow_package_imports_flow_tenant_space",
        ),
        Index(
            "ix_flow_package_imports_tenant_space_created",
            "tenant_id",
            "space_id",
            "created_at",
        ),
        Index(
            "ix_flow_package_imports_space_checksum_created",
            "space_id",
            "content_checksum",
            "created_at",
        ),
    )


class FlowRuns(BasePublic):
    """Stores one execution of a published Flow version. Writer: FlowRunRepository. Purpose: persist principal, status, input, output, and lifecycle anchors."""

    flow_id: Mapped[UUID] = mapped_column(
        ForeignKey(Flows.id, ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    flow_version: Mapped[int] = mapped_column(nullable=False)
    principal_type: Mapped[str] = mapped_column(
        sa.String(32),
        nullable=False,
        server_default="user",
    )
    principal_user_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Users.id, ondelete="RESTRICT"),
        nullable=True,
    )
    principal_service_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("service_principals.id", ondelete="RESTRICT"),
        nullable=True,
    )
    created_by_api_key_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("api_keys_v2.id", ondelete="SET NULL"),
        nullable=True,
    )
    runtime_service_permission: Mapped[Optional[str]] = mapped_column(
        sa.String(32),
        nullable=True,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    trace_id: Mapped[UUID] = mapped_column(default=uuid4, nullable=False, index=True)
    idempotency_key: Mapped[Optional[str]] = mapped_column(
        sa.String(255),
        nullable=True,
    )
    request_fingerprint: Mapped[Optional[str]] = mapped_column(
        sa.String(64),
        nullable=True,
    )
    revision: Mapped[int] = mapped_column(
        nullable=False,
        server_default="1",
        comment=(
            "Monotonic lifecycle compare-and-swap token; its value on entry to "
            "queued identifies the dispatch epoch."
        ),
    )
    status: Mapped[str] = mapped_column(
        sa.String(32),
        nullable=False,
        server_default="queued",
        index=True,
    )
    dispatch_pending_since: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    dispatch_attempt_count: Mapped[int] = mapped_column(
        nullable=False,
        server_default="0",
    )
    dispatch_last_attempt_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    dispatch_last_error: Mapped[Optional[dict[str, object]]] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
    dispatch_next_attempt_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    dispatched_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    dispatch_exhausted_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(sa.DateTime(timezone=True))
    started_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    input_payload_json: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )
    output_payload_json: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )
    error_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    job_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Jobs.id, ondelete="SET NULL"),
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint(
            "principal_type IN ('user','service_key')",
            name="ck_flow_runs_principal_type",
        ),
        CheckConstraint(
            "("
            "(principal_type = 'user' "
            "AND principal_user_id IS NOT NULL "
            "AND principal_service_id IS NULL "
            "AND runtime_service_permission IS NULL) "
            "OR "
            "(principal_type = 'service_key' "
            "AND principal_user_id IS NULL "
            "AND principal_service_id IS NOT NULL "
            "AND runtime_service_permission IN ('read','write','admin'))"
            ")",
            name="ck_flow_runs_principal_identity",
        ),
        CheckConstraint(
            f"status IN ({_check_values(FLOW_RUN_STATUS_VALUES)})",
            name="ck_flow_runs_status",
        ),
        CheckConstraint(
            "dispatch_attempt_count >= 0",
            name="ck_flow_runs_dispatch_attempt_count_nonnegative",
        ),
        CheckConstraint(
            "dispatch_last_error IS NULL "
            "OR jsonb_typeof(dispatch_last_error) = 'object'",
            name="ck_flow_runs_dispatch_last_error_object",
        ),
        ForeignKeyConstraint(
            ["flow_id", "tenant_id"],
            ["flows.id", "flows.tenant_id"],
            ondelete="CASCADE",
            name="fk_flow_runs_flow_tenant",
        ),
        ForeignKeyConstraint(
            ["flow_id", "flow_version"],
            ["flow_versions.flow_id", "flow_versions.version"],
            ondelete="RESTRICT",
            name="fk_flow_runs_flow_version",
        ),
        UniqueConstraint("id", "tenant_id", name="uq_flow_runs_id_tenant_id"),
        UniqueConstraint("id", "flow_id", name="uq_flow_runs_id_flow_id"),
        Index("ix_flow_runs_flow_id_status", "flow_id", "status"),
        Index("ix_flow_runs_tenant_created_at", "tenant_id", "created_at"),
        Index(
            "ix_flow_runs_queued_dispatch_due",
            "tenant_id",
            "dispatch_next_attempt_at",
            "id",
            postgresql_where=sa.text(
                "status = 'queued' "
                "AND dispatch_next_attempt_at IS NOT NULL "
                "AND dispatch_exhausted_at IS NULL"
            ),
        ),
        Index(
            "uq_flow_runs_idempotency_user_key",
            "tenant_id",
            "flow_id",
            "principal_user_id",
            "idempotency_key",
            unique=True,
            postgresql_where=sa.text(
                "principal_type = 'user' AND idempotency_key IS NOT NULL"
            ),
        ),
        Index(
            "uq_flow_runs_idempotency_service_key",
            "tenant_id",
            "flow_id",
            "principal_service_id",
            "idempotency_key",
            unique=True,
            postgresql_where=sa.text(
                "principal_type = 'service_key' AND idempotency_key IS NOT NULL"
            ),
        ),
        Index(
            "ix_flow_runs_service_principal_created_at",
            "tenant_id",
            "principal_service_id",
            sa.text("created_at DESC"),
            postgresql_where=sa.text("principal_type = 'service_key'"),
        ),
        Index(
            "ix_flow_runs_running_updated_at",
            "status",
            "updated_at",
            postgresql_where=sa.text("status = 'running'"),
        ),
        Index(
            "ix_flow_runs_terminal_retention_anchor",
            sa.text("coalesce(finished_at, created_at)"),
            "id",
            postgresql_include=("flow_id",),
            postgresql_where=sa.text(
                FLOW_RUN_TERMINAL_RETENTION_ANCHOR_INDEX_PREDICATE
            ),
        ),
    )


class FlowStepResults(BasePublic):
    """Stores current per-step runtime results. Writer: FlowRunRepository. Purpose: keep step status, payloads, diagnostics, and output metadata per run."""

    flow_run_id: Mapped[UUID] = mapped_column(
        ForeignKey(FlowRuns.id, ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    flow_id: Mapped[UUID] = mapped_column(
        ForeignKey(Flows.id, ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    step_id: Mapped[UUID] = mapped_column(nullable=False)
    step_order: Mapped[int] = mapped_column(nullable=False)
    assistant_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Assistants.id, ondelete="SET NULL"),
        nullable=True,
    )
    current_attempt_no: Mapped[Optional[int]] = mapped_column(
        nullable=True,
        server_default="1",
    )
    input_payload_json: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )
    effective_prompt: Mapped[Optional[str]] = mapped_column(nullable=True)
    output_payload_json: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )
    model_parameters_json: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )
    num_tokens_input: Mapped[Optional[int]] = mapped_column(nullable=True)
    num_tokens_output: Mapped[Optional[int]] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(
        sa.String(32),
        nullable=False,
        server_default="pending",
    )
    error_code: Mapped[Optional[str]] = mapped_column(nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(nullable=True)
    flow_step_execution_hash: Mapped[Optional[str]] = mapped_column(nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "step_order >= 1",
            name="ck_flow_step_results_step_order_positive",
        ),
        CheckConstraint(
            "current_attempt_no IS NULL OR current_attempt_no >= 1",
            name="ck_flow_step_results_current_attempt_no_positive",
        ),
        CheckConstraint(
            f"status IN ({_check_values(FLOW_STEP_RESULT_STATUS_VALUES)})",
            name="ck_flow_step_results_status",
        ),
        ForeignKeyConstraint(
            ["flow_run_id", "tenant_id"],
            ["flow_runs.id", "flow_runs.tenant_id"],
            ondelete="CASCADE",
            name="fk_flow_step_results_run_tenant",
        ),
        ForeignKeyConstraint(
            ["flow_run_id", "flow_id"],
            ["flow_runs.id", "flow_runs.flow_id"],
            ondelete="CASCADE",
            name="fk_flow_step_results_run_flow",
        ),
        UniqueConstraint(
            "flow_run_id", "step_id", name="uq_flow_step_results_run_step"
        ),
        Index(
            "ix_flow_step_results_run_flow_step", "flow_run_id", "flow_id", "step_id"
        ),
        Index("ix_flow_step_results_assistant_id", "assistant_id"),
    )


class FlowRunRerunOperations(BasePublic):
    """Stores rerun requests for existing Flow runs. Writer: FlowRunRerunRepository. Purpose: record rerun intent, invalidation, and terminal rerun outcome."""

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            Tenants.id,
            ondelete="CASCADE",
            name="fk_rerun_operations_tenant",
        ),
        nullable=False,
        index=True,
    )
    flow_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            Flows.id,
            ondelete="CASCADE",
            name="fk_rerun_operations_flow",
        ),
        nullable=False,
        index=True,
    )
    flow_run_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    rerun_step_id: Mapped[UUID] = mapped_column(nullable=False)
    rerun_step_order: Mapped[int] = mapped_column(nullable=False)
    root_attempt_no: Mapped[int] = mapped_column(nullable=False)
    root_attempt_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(
            "flow_step_attempts.id",
            ondelete="SET NULL",
            name="fk_rerun_operations_root_attempt",
        ),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        sa.String(32),
        nullable=False,
        server_default=FlowRunRerunOperationStatus.QUEUED.value,
    )
    request_fingerprint: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    expected_run_revision: Mapped[int] = mapped_column(nullable=False)
    accepted_run_revision: Mapped[int] = mapped_column(nullable=False)
    reason: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    input_payload_json: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )
    root_step_input_override_requested: Mapped[bool] = mapped_column(nullable=False)
    requested_by_principal_type: Mapped[str] = mapped_column(
        sa.String(32), nullable=False
    )
    requested_by_user_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(
            Users.id,
            ondelete="RESTRICT",
            name="fk_rerun_operations_requested_by_user",
        ),
        nullable=True,
    )
    requested_by_service_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(
            "service_principals.id",
            ondelete="RESTRICT",
            name="fk_rerun_operations_requested_by_service",
        ),
        nullable=True,
    )
    failure_code: Mapped[Optional[str]] = mapped_column(sa.String(64), nullable=True)
    failure_message: Mapped[Optional[str]] = mapped_column(nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            f"status IN ({_check_values(FLOW_RUN_RERUN_OPERATION_STATUS_VALUES)})",
            name="ck_flow_run_rerun_operations_status",
        ),
        CheckConstraint(
            "("
            "requested_by_principal_type = 'user' "
            "AND requested_by_user_id IS NOT NULL "
            "AND requested_by_service_id IS NULL"
            ") OR ("
            "requested_by_principal_type = 'service_key' "
            "AND requested_by_user_id IS NULL "
            "AND requested_by_service_id IS NOT NULL"
            ")",
            name="ck_flow_run_rerun_operations_requester_principal",
        ),
        ForeignKeyConstraint(
            ["flow_run_id", "tenant_id"],
            ["flow_runs.id", "flow_runs.tenant_id"],
            ondelete="CASCADE",
            name="fk_flow_run_rerun_operations_run_tenant",
        ),
        ForeignKeyConstraint(
            ["flow_run_id", "flow_id"],
            ["flow_runs.id", "flow_runs.flow_id"],
            ondelete="CASCADE",
            name="fk_flow_run_rerun_operations_run_flow",
        ),
        UniqueConstraint(
            "tenant_id",
            "flow_run_id",
            "request_fingerprint",
            name="uq_flow_run_rerun_operations_request_fingerprint",
        ),
        Index("ix_flow_run_rerun_operations_run_status", "flow_run_id", "status"),
        Index(
            "uq_flow_run_rerun_operations_one_active_per_run",
            "flow_run_id",
            unique=True,
            postgresql_where=sa.text("status IN ('queued', 'running')"),
        ),
        Index(
            "ix_flow_run_rerun_operations_tenant_created_at",
            "tenant_id",
            "created_at",
        ),
        Index(
            "ix_flow_run_rerun_operations_run_step",
            "flow_run_id",
            "rerun_step_id",
        ),
    )


class FlowStepAttempts(BasePublic):
    """Stores individual step execution attempts. Writer: FlowRunRepository. Purpose: preserve retry diagnostics, timings, prompts, and raw attempt payloads."""

    flow_run_id: Mapped[UUID] = mapped_column(
        ForeignKey(FlowRuns.id, ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    flow_id: Mapped[UUID] = mapped_column(
        ForeignKey(Flows.id, ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    step_id: Mapped[UUID] = mapped_column(nullable=False)
    step_order: Mapped[int] = mapped_column(nullable=False)
    attempt_no: Mapped[int] = mapped_column(nullable=False)
    rerun_operation_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(
            FlowRunRerunOperations.id,
            ondelete="SET NULL",
            name="fk_step_attempts_rerun_operation",
        ),
        nullable=True,
    )
    predecessor_attempt_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(
            "flow_step_attempts.id",
            ondelete="SET NULL",
            name="fk_step_attempts_predecessor",
        ),
        nullable=True,
    )
    superseded_by_attempt_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(
            "flow_step_attempts.id",
            ondelete="SET NULL",
            name="fk_step_attempts_superseded_by",
        ),
        nullable=True,
    )
    celery_task_id: Mapped[Optional[str]] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    error_code: Mapped[Optional[str]] = mapped_column(nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(nullable=True)
    requested_model: Mapped[Optional[str]] = mapped_column(nullable=True)
    response_model: Mapped[Optional[str]] = mapped_column(nullable=True)
    provider: Mapped[Optional[str]] = mapped_column(nullable=True)
    finish_reason: Mapped[Optional[str]] = mapped_column(nullable=True)
    provider_response_id: Mapped[Optional[str]] = mapped_column(nullable=True)
    num_tokens_input: Mapped[Optional[int]] = mapped_column(nullable=True)
    num_tokens_output: Mapped[Optional[int]] = mapped_column(nullable=True)
    provenance_json: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )
    input_payload_json: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )
    output_payload_json: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )
    flow_step_execution_hash: Mapped[Optional[str]] = mapped_column(nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(sa.DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "step_order >= 1",
            name="ck_flow_step_attempts_step_order_positive",
        ),
        CheckConstraint(
            "attempt_no >= 1",
            name="ck_flow_step_attempts_attempt_no_positive",
        ),
        CheckConstraint(
            f"status IN ({_check_values(FLOW_STEP_ATTEMPT_STATUS_VALUES)})",
            name="ck_flow_step_attempts_status",
        ),
        ForeignKeyConstraint(
            ["flow_run_id", "tenant_id"],
            ["flow_runs.id", "flow_runs.tenant_id"],
            ondelete="CASCADE",
            name="fk_flow_step_attempts_run_tenant",
        ),
        ForeignKeyConstraint(
            ["flow_run_id", "flow_id"],
            ["flow_runs.id", "flow_runs.flow_id"],
            ondelete="CASCADE",
            name="fk_flow_step_attempts_run_flow",
        ),
        UniqueConstraint(
            "flow_run_id",
            "step_id",
            "attempt_no",
            name="uq_flow_step_attempts_run_step_attempt",
        ),
        Index(
            "ix_flow_step_attempts_run_flow_step_attempt",
            "flow_run_id",
            "flow_id",
            "step_id",
            "attempt_no",
        ),
        Index("ix_flow_step_attempts_rerun_operation", "rerun_operation_id"),
        Index("ix_flow_step_attempts_predecessor_attempt", "predecessor_attempt_id"),
        Index(
            "ix_flow_step_attempts_superseded_by_attempt",
            "superseded_by_attempt_id",
        ),
    )


class FlowRunRerunInvalidatedSteps(BasePublic):
    """Stores step invalidation markers from reruns. Writer: FlowRunRerunRepository. Purpose: preserve rerun lineage without deleting earlier step history immediately."""

    operation_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            FlowRunRerunOperations.id,
            ondelete="CASCADE",
            name="fk_rerun_invalidated_steps_operation",
        ),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            Tenants.id,
            ondelete="CASCADE",
            name="fk_rerun_invalidated_steps_tenant",
        ),
        nullable=False,
        index=True,
    )
    flow_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            Flows.id,
            ondelete="CASCADE",
            name="fk_rerun_invalidated_steps_flow",
        ),
        nullable=False,
        index=True,
    )
    flow_run_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    step_id: Mapped[UUID] = mapped_column(nullable=False)
    step_order: Mapped[int] = mapped_column(nullable=False)
    invalidation_order: Mapped[int] = mapped_column(nullable=False)
    role: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    dependency_sources_json: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=sa.text("'[]'::jsonb"),
    )
    prior_step_result_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(
            FlowStepResults.id,
            ondelete="SET NULL",
            name="fk_rerun_invalidated_steps_prior_result",
        ),
        nullable=True,
    )
    prior_attempt_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(
            FlowStepAttempts.id,
            ondelete="SET NULL",
            name="fk_rerun_invalidated_steps_prior_attempt",
        ),
        nullable=True,
    )
    new_attempt_no: Mapped[Optional[int]] = mapped_column(nullable=True)
    new_attempt_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(
            FlowStepAttempts.id,
            ondelete="SET NULL",
            name="fk_rerun_invalidated_steps_new_attempt",
        ),
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint(
            f"role IN ({_check_values(FLOW_RUN_RERUN_INVALIDATION_ROLE_VALUES)})",
            name="ck_flow_run_rerun_invalidated_steps_role",
        ),
        ForeignKeyConstraint(
            ["flow_run_id", "tenant_id"],
            ["flow_runs.id", "flow_runs.tenant_id"],
            ondelete="CASCADE",
            name="fk_flow_run_rerun_invalidated_steps_run_tenant",
        ),
        ForeignKeyConstraint(
            ["flow_run_id", "flow_id"],
            ["flow_runs.id", "flow_runs.flow_id"],
            ondelete="CASCADE",
            name="fk_flow_run_rerun_invalidated_steps_run_flow",
        ),
        UniqueConstraint(
            "operation_id",
            "step_id",
            name="uq_flow_run_rerun_invalidated_steps_operation_step",
        ),
        UniqueConstraint(
            "operation_id",
            "invalidation_order",
            name="uq_flow_run_rerun_invalidated_steps_operation_order",
        ),
        Index(
            "ix_flow_run_rerun_invalidated_steps_run_step",
            "flow_run_id",
            "step_id",
        ),
        Index(
            "ix_flow_run_rerun_invalidated_steps_prior_attempt",
            "prior_attempt_id",
        ),
        Index(
            "ix_flow_run_rerun_invalidated_steps_new_attempt",
            "new_attempt_id",
        ),
    )


class FlowRunReviewCheckpoints(BasePublic):
    """Stores human review pauses for Flow runs. Writer: FlowRunReviewCheckpointRepository. Purpose: track editable checkpoint state, revisions, decisions, and expiry."""

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            Tenants.id,
            ondelete="CASCADE",
            name="fk_review_checkpoints_tenant",
        ),
        nullable=False,
        index=True,
    )
    flow_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            Flows.id,
            ondelete="CASCADE",
            name="fk_review_checkpoints_flow",
        ),
        nullable=False,
        index=True,
    )
    flow_run_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    step_id: Mapped[UUID] = mapped_column(nullable=False)
    step_order: Mapped[int] = mapped_column(nullable=False)
    attempt_no: Mapped[int] = mapped_column(nullable=False)
    state: Mapped[str] = mapped_column(
        sa.String(32),
        nullable=False,
        server_default=FlowRunReviewCheckpointState.AWAITING_REVIEW.value,
    )
    revision: Mapped[int] = mapped_column(nullable=False, server_default="1")
    schema_version: Mapped[int] = mapped_column(nullable=False, server_default="1")
    original_payload_json: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
    )
    current_payload_json: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
    )
    step_label: Mapped[Optional[str]] = mapped_column(sa.Text(), nullable=True)
    review_mode: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    output_type: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    output_contract_json: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
    )
    requester_user_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(
            Users.id,
            ondelete="SET NULL",
            name="fk_review_checkpoints_requester_user",
        ),
        nullable=True,
    )
    requester_service_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(
            "service_principals.id",
            ondelete="SET NULL",
            name="fk_review_checkpoints_requester_service",
        ),
        nullable=True,
    )
    requester_principal_type: Mapped[str] = mapped_column(
        sa.String(32),
        nullable=False,
    )
    decided_by_user_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(
            Users.id,
            ondelete="SET NULL",
            name="fk_review_checkpoints_decided_by_user",
        ),
        nullable=True,
    )
    decided_by_service_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(
            "service_principals.id",
            ondelete="SET NULL",
            name="fk_review_checkpoints_decided_by_service",
        ),
        nullable=True,
    )
    decided_by_principal_type: Mapped[Optional[str]] = mapped_column(
        sa.String(32),
        nullable=True,
    )
    next_step_ids_json: Mapped[Optional[list[str]]] = mapped_column(
        JSONB, nullable=True
    )
    resume_idempotency_key: Mapped[Optional[str]] = mapped_column(
        sa.String(255),
        nullable=True,
    )
    edited_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
    )
    approved_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
    )
    rejected_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
    )
    resumed_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
    )
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
    )
    expired_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint(
            f"state IN ({_check_values(FLOW_RUN_REVIEW_CHECKPOINT_STATE_VALUES)})",
            name="ck_flow_run_review_checkpoints_state",
        ),
        CheckConstraint(
            "revision >= 1",
            name="ck_flow_run_review_checkpoints_revision",
        ),
        CheckConstraint(
            "schema_version >= 1",
            name="ck_flow_run_review_checkpoints_schema_version",
        ),
        CheckConstraint(
            f"review_mode IN ({_check_values(FLOW_STEP_REVIEW_MODE_VALUES)})",
            name="ck_flow_run_review_checkpoints_review_mode",
        ),
        CheckConstraint(
            f"output_type IN ({_check_values(FLOW_STEP_OUTPUT_TYPE_VALUES)})",
            name="ck_flow_run_review_checkpoints_output_type",
        ),
        CheckConstraint(
            "("
            "requester_principal_type = 'user' "
            "AND requester_user_id IS NOT NULL "
            "AND requester_service_id IS NULL"
            ") OR ("
            "requester_principal_type = 'service_key' "
            "AND requester_user_id IS NULL "
            "AND requester_service_id IS NOT NULL"
            ")",
            name="ck_flow_run_review_checkpoints_requester_principal",
        ),
        CheckConstraint(
            "decided_by_principal_type IS NULL "
            "OR ("
            "decided_by_principal_type = 'user' "
            "AND decided_by_user_id IS NOT NULL "
            "AND decided_by_service_id IS NULL"
            ") OR ("
            "decided_by_principal_type = 'service_key' "
            "AND decided_by_user_id IS NULL "
            "AND decided_by_service_id IS NOT NULL"
            ")",
            name="ck_flow_run_review_checkpoints_decider_principal",
        ),
        ForeignKeyConstraint(
            ["flow_run_id", "tenant_id"],
            ["flow_runs.id", "flow_runs.tenant_id"],
            ondelete="CASCADE",
            name="fk_flow_run_review_checkpoints_run_tenant",
        ),
        ForeignKeyConstraint(
            ["flow_run_id", "flow_id"],
            ["flow_runs.id", "flow_runs.flow_id"],
            ondelete="CASCADE",
            name="fk_flow_run_review_checkpoints_run_flow",
        ),
        ForeignKeyConstraint(
            ["flow_run_id", "step_id", "attempt_no"],
            [
                "flow_step_attempts.flow_run_id",
                "flow_step_attempts.step_id",
                "flow_step_attempts.attempt_no",
            ],
            ondelete="RESTRICT",
            name="fk_flow_run_review_checkpoints_step_attempt",
        ),
        UniqueConstraint(
            "flow_run_id",
            "step_id",
            "attempt_no",
            name="uq_flow_run_review_checkpoints_run_step_attempt",
        ),
        Index(
            "uq_flow_run_review_checkpoints_one_active_per_run",
            "flow_run_id",
            unique=True,
            postgresql_where=sa.text(
                "state IN ('awaiting_review', 'edited', 'approved')"
            ),
        ),
        Index(
            "uq_flow_run_review_checkpoints_resume_key",
            "tenant_id",
            "flow_run_id",
            "resume_idempotency_key",
            unique=True,
            postgresql_where=sa.text("resume_idempotency_key IS NOT NULL"),
        ),
        Index(
            "ix_flow_run_review_checkpoints_run_step_attempt",
            "flow_run_id",
            "step_id",
            "attempt_no",
        ),
        Index(
            "ix_flow_run_review_checkpoints_tenant_created_at",
            "tenant_id",
            "created_at",
        ),
        Index(
            "ix_flow_run_review_checkpoints_tenant_expires_at_reconcilable",
            "tenant_id",
            "expires_at",
            postgresql_where=sa.text("state IN ('awaiting_review', 'edited')"),
        ),
    )


class FlowRunStepInputFiles(BasePublic):
    """Stores files bound as step inputs for a run attempt. Writer: FlowRunRepository. Purpose: make runtime file override intent relational and auditable."""

    flow_run_id: Mapped[UUID] = mapped_column(
        nullable=False,
        index=True,
    )
    flow_id: Mapped[UUID] = mapped_column(
        ForeignKey(Flows.id, ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    step_id: Mapped[UUID] = mapped_column(nullable=False)
    step_order: Mapped[int] = mapped_column(nullable=False)
    attempt_no: Mapped[int] = mapped_column(nullable=False)
    file_id: Mapped[UUID] = mapped_column(
        ForeignKey(Files.id, ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    ordinal: Mapped[int] = mapped_column(nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["flow_run_id", "tenant_id"],
            ["flow_runs.id", "flow_runs.tenant_id"],
            ondelete="CASCADE",
            name="fk_flow_run_step_input_files_run_tenant",
        ),
        ForeignKeyConstraint(
            ["flow_run_id", "flow_id"],
            ["flow_runs.id", "flow_runs.flow_id"],
            ondelete="CASCADE",
            name="fk_flow_run_step_input_files_run_flow",
        ),
        ForeignKeyConstraint(
            ["file_id", "flow_id", "tenant_id"],
            [
                "flow_runtime_uploaded_files.file_id",
                "flow_runtime_uploaded_files.flow_id",
                "flow_runtime_uploaded_files.tenant_id",
            ],
            ondelete="RESTRICT",
            name="fk_flow_run_step_input_files_runtime_upload",
        ),
        CheckConstraint(
            "attempt_no >= 1",
            name="ck_flow_run_step_input_files_attempt_no_positive",
        ),
        UniqueConstraint(
            "flow_run_id",
            "step_id",
            "attempt_no",
            "file_id",
            name="uq_flow_run_step_input_files_run_step_attempt_file",
        ),
        UniqueConstraint(
            "flow_run_id",
            "step_id",
            "attempt_no",
            "ordinal",
            name="uq_flow_run_step_input_files_run_step_attempt_ordinal",
        ),
        Index(
            "ix_flow_run_step_input_files_tenant_file",
            "tenant_id",
            "file_id",
        ),
        Index(
            "ix_flow_run_step_input_files_run_step_attempt",
            "flow_run_id",
            "step_id",
            "attempt_no",
        ),
        Index(
            "ix_flow_run_step_input_files_flow_step",
            "flow_id",
            "step_id",
        ),
    )


class FlowRunStepResultFiles(BasePublic):
    """Stores files produced by step results. Writer: FlowRunRepository. Purpose: connect generated artifacts to the run, step, attempt, and file owner graph."""

    flow_run_id: Mapped[UUID] = mapped_column(
        nullable=False,
        index=True,
    )
    flow_id: Mapped[UUID] = mapped_column(
        ForeignKey(Flows.id, ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    step_result_id: Mapped[UUID] = mapped_column(
        ForeignKey(FlowStepResults.id, ondelete="CASCADE"),
        nullable=False,
    )
    step_id: Mapped[UUID] = mapped_column(nullable=False)
    step_order: Mapped[int] = mapped_column(nullable=False)
    attempt_no: Mapped[int] = mapped_column(nullable=False)
    file_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    ordinal: Mapped[int] = mapped_column(nullable=False)
    source: Mapped[str] = mapped_column(sa.String(32), nullable=False)

    __table_args__ = (
        CheckConstraint(
            f"source IN ({_check_values(FLOW_RUN_STEP_RESULT_FILE_SOURCE_VALUES)})",
            name="ck_flow_run_step_result_files_source",
        ),
        ForeignKeyConstraint(
            ["flow_run_id", "tenant_id"],
            ["flow_runs.id", "flow_runs.tenant_id"],
            ondelete="CASCADE",
            name="fk_flow_run_step_result_files_run_tenant",
        ),
        ForeignKeyConstraint(
            ["flow_run_id", "flow_id"],
            ["flow_runs.id", "flow_runs.flow_id"],
            ondelete="CASCADE",
            name="fk_flow_run_step_result_files_run_flow",
        ),
        ForeignKeyConstraint(
            ["file_id", "tenant_id"],
            ["files.id", "files.tenant_id"],
            ondelete="RESTRICT",
            name="fk_flow_run_step_result_files_file_tenant",
        ),
        ForeignKeyConstraint(
            ["flow_run_id", "step_id", "attempt_no"],
            [
                "flow_step_attempts.flow_run_id",
                "flow_step_attempts.step_id",
                "flow_step_attempts.attempt_no",
            ],
            ondelete="CASCADE",
            name="fk_flow_run_step_result_files_step_attempt",
        ),
        UniqueConstraint(
            "flow_run_id",
            "step_id",
            "attempt_no",
            "file_id",
            name="uq_flow_run_step_result_files_run_step_attempt_file",
        ),
        UniqueConstraint(
            "flow_run_id",
            "step_id",
            "attempt_no",
            "ordinal",
            name="uq_flow_run_step_result_files_run_step_attempt_ordinal",
        ),
        Index(
            "ix_flow_run_step_result_files_tenant_file",
            "tenant_id",
            "file_id",
        ),
        Index(
            "ix_flow_run_step_result_files_run_step_attempt",
            "flow_run_id",
            "step_id",
            "attempt_no",
        ),
        Index(
            "ix_flow_run_step_result_files_step_result",
            "step_result_id",
        ),
    )


class FlowRunAuditOutbox(BasePublic):
    """Stores durable Flow lifecycle audit intents. Writer: FlowRunAuditOutboxRepository. Purpose: deliver content-free audit logs while preserving run transaction order."""

    __tablename__ = "flow_run_audit_outbox"  # type: ignore[assignment]

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    flow_id: Mapped[UUID] = mapped_column(
        ForeignKey(Flows.id, ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    flow_run_id: Mapped[UUID] = mapped_column(
        nullable=False,
        index=True,
    )
    run_revision: Mapped[int] = mapped_column(
        nullable=False,
        server_default="1",
    )
    review_checkpoint_id: Mapped[Optional[UUID]] = mapped_column(
        nullable=True,
        index=True,
    )
    checkpoint_revision: Mapped[Optional[int]] = mapped_column(nullable=True)
    description: Mapped[str] = mapped_column(nullable=False)
    action: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    entity_id: Mapped[UUID] = mapped_column(nullable=False)
    actor_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Users.id, ondelete="SET NULL"),
        nullable=True,
    )
    actor_type: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    actor_api_key_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("api_keys_v2.id", ondelete="SET NULL"),
        nullable=True,
    )
    source: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    target_status: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    error_code: Mapped[Optional[str]] = mapped_column(nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(nullable=True)
    delivery_status: Mapped[str] = mapped_column(
        sa.String(32),
        nullable=False,
        server_default=FlowOutboxDeliveryStatus.PENDING.value,
    )
    delivery_attempts: Mapped[int] = mapped_column(
        nullable=False,
        server_default="0",
    )
    next_delivery_at: Mapped[Optional[datetime]] = mapped_column(
        sa.TIMESTAMP(timezone=True),
        nullable=True,
        server_default=sa.func.now(),
    )
    delivered_at: Mapped[Optional[datetime]] = mapped_column(
        sa.TIMESTAMP(timezone=True),
        nullable=True,
    )
    dead_lettered_at: Mapped[Optional[datetime]] = mapped_column(
        sa.TIMESTAMP(timezone=True),
        nullable=True,
    )
    delivery_last_error: Mapped[Optional[str]] = mapped_column(sa.Text(), nullable=True)

    __table_args__ = (
        Index(
            "uq_flow_run_audit_outbox_run_revision",
            "flow_run_id",
            "run_revision",
            unique=True,
            postgresql_where=sa.text("review_checkpoint_id IS NULL"),
        ),
        Index(
            "uq_flow_run_audit_outbox_checkpoint_revision",
            "review_checkpoint_id",
            "checkpoint_revision",
            unique=True,
            postgresql_where=sa.text("review_checkpoint_id IS NOT NULL"),
        ),
        ForeignKeyConstraint(
            ["flow_run_id", "tenant_id"],
            ["flow_runs.id", "flow_runs.tenant_id"],
            ondelete="RESTRICT",
            name="fk_flow_run_audit_outbox_run_tenant",
        ),
        ForeignKeyConstraint(
            ["flow_run_id", "flow_id"],
            ["flow_runs.id", "flow_runs.flow_id"],
            ondelete="RESTRICT",
            name="fk_flow_run_audit_outbox_run_flow",
        ),
        ForeignKeyConstraint(
            ["review_checkpoint_id"],
            ["flow_run_review_checkpoints.id"],
            ondelete="RESTRICT",
            name="fk_flow_run_audit_outbox_review_checkpoint",
        ),
        CheckConstraint(
            f"target_status IN ({_check_values(FLOW_RUN_AUDIT_TARGET_STATUS_VALUES)})",
            name="ck_flow_run_audit_outbox_target_status",
        ),
        CheckConstraint(
            "("
            "(review_checkpoint_id IS NULL AND checkpoint_revision IS NULL) "
            "OR "
            "(review_checkpoint_id IS NOT NULL AND checkpoint_revision IS NOT NULL)"
            ")",
            name="ck_flow_run_audit_outbox_checkpoint_key",
        ),
        CheckConstraint(
            "description = action || ':' || source",
            name="ck_flow_run_audit_outbox_description",
        ),
        CheckConstraint(
            f"source IN ({_check_values(FLOW_RUN_LIFECYCLE_SOURCE_VALUES)})",
            name="ck_flow_run_audit_outbox_source",
        ),
        CheckConstraint(
            "delivery_attempts >= 0",
            name="ck_flow_run_audit_outbox_delivery_attempts",
        ),
        CheckConstraint(
            "delivery_status IN "
            f"({_check_values(FLOW_RUN_AUDIT_OUTBOX_DELIVERY_STATUS_VALUES)})",
            name="ck_flow_run_audit_outbox_delivery_status",
        ),
        CheckConstraint(
            "("
            "(delivery_status = 'pending' "
            "AND delivered_at IS NULL "
            "AND dead_lettered_at IS NULL) "
            "OR "
            "(delivery_status = 'delivered' "
            "AND delivered_at IS NOT NULL "
            "AND dead_lettered_at IS NULL) "
            "OR "
            "(delivery_status = 'dead_lettered' "
            "AND delivered_at IS NULL "
            "AND dead_lettered_at IS NOT NULL)"
            ")",
            name="ck_flow_run_audit_outbox_delivery_timestamps",
        ),
        Index("ix_flow_run_audit_outbox_tenant_created", "tenant_id", "created_at"),
        Index("ix_flow_run_audit_outbox_action", "action"),
        Index(
            "ix_flow_run_audit_outbox_pending_delivery",
            "next_delivery_at",
            "created_at",
            postgresql_where=sa.text("delivery_status = 'pending'"),
        ),
        Index(
            "ix_flow_run_audit_outbox_dead_lettered",
            "dead_lettered_at",
            postgresql_where=sa.text("delivery_status = 'dead_lettered'"),
        ),
    )


class FlowRunWebhookDeliveries(BasePublic):
    """Stores HTTP step delivery outbox rows. Writer: FlowRunWebhookDeliveryRepository. Purpose: claim, retry, dead-letter, and finalize webhook deliveries durably."""

    __tablename__ = "flow_run_webhook_deliveries"  # type: ignore[assignment]

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    flow_id: Mapped[UUID] = mapped_column(
        ForeignKey(Flows.id, ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    flow_run_id: Mapped[UUID] = mapped_column(
        nullable=False,
        index=True,
    )
    step_id: Mapped[UUID] = mapped_column(nullable=False)
    step_order: Mapped[int] = mapped_column(nullable=False)
    attempt_no: Mapped[int] = mapped_column(nullable=False)
    idempotency_key: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    payload_ref: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    delivery_status: Mapped[str] = mapped_column(
        sa.String(32),
        nullable=False,
        server_default=FlowOutboxDeliveryStatus.PENDING.value,
    )
    delivery_attempts: Mapped[int] = mapped_column(
        nullable=False,
        server_default="0",
    )
    next_delivery_at: Mapped[Optional[datetime]] = mapped_column(
        sa.TIMESTAMP(timezone=True),
        nullable=True,
        server_default=sa.func.now(),
    )
    claim_token: Mapped[Optional[UUID]] = mapped_column(nullable=True)
    claimed_at: Mapped[Optional[datetime]] = mapped_column(
        sa.TIMESTAMP(timezone=True),
        nullable=True,
    )
    claim_expires_at: Mapped[Optional[datetime]] = mapped_column(
        sa.TIMESTAMP(timezone=True),
        nullable=True,
    )
    delivered_at: Mapped[Optional[datetime]] = mapped_column(
        sa.TIMESTAMP(timezone=True),
        nullable=True,
    )
    dead_lettered_at: Mapped[Optional[datetime]] = mapped_column(
        sa.TIMESTAMP(timezone=True),
        nullable=True,
    )
    delivery_last_error: Mapped[Optional[str]] = mapped_column(sa.Text(), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "flow_run_id",
            "step_id",
            "attempt_no",
            name="uq_flow_run_webhook_deliveries_attempt",
        ),
        ForeignKeyConstraint(
            ["flow_run_id", "tenant_id"],
            ["flow_runs.id", "flow_runs.tenant_id"],
            ondelete="RESTRICT",
            name="fk_flow_run_webhook_deliveries_run_tenant",
        ),
        ForeignKeyConstraint(
            ["flow_run_id", "flow_id"],
            ["flow_runs.id", "flow_runs.flow_id"],
            ondelete="RESTRICT",
            name="fk_flow_run_webhook_deliveries_run_flow",
        ),
        ForeignKeyConstraint(
            ["flow_run_id", "step_id", "attempt_no"],
            [
                "flow_step_attempts.flow_run_id",
                "flow_step_attempts.step_id",
                "flow_step_attempts.attempt_no",
            ],
            ondelete="RESTRICT",
            name="fk_flow_run_webhook_deliveries_step_attempt",
        ),
        CheckConstraint(
            "attempt_no >= 1",
            name="ck_flow_run_webhook_deliveries_attempt_no",
        ),
        CheckConstraint(
            "delivery_attempts >= 0",
            name="ck_flow_run_webhook_deliveries_delivery_attempts",
        ),
        CheckConstraint(
            "idempotency_key <> ''",
            name="ck_flow_run_webhook_deliveries_idempotency_key",
        ),
        CheckConstraint(
            "payload_ref <> ''",
            name="ck_flow_run_webhook_deliveries_payload_ref",
        ),
        CheckConstraint(
            "delivery_status IN "
            f"({_check_values(FLOW_RUN_WEBHOOK_DELIVERY_STATUS_VALUES)})",
            name="ck_flow_run_webhook_deliveries_status",
        ),
        CheckConstraint(
            "("
            "(delivery_status = 'pending' "
            "AND delivered_at IS NULL "
            "AND dead_lettered_at IS NULL) "
            "OR "
            "(delivery_status = 'delivered' "
            "AND delivered_at IS NOT NULL "
            "AND dead_lettered_at IS NULL) "
            "OR "
            "(delivery_status = 'dead_lettered' "
            "AND delivered_at IS NULL "
            "AND dead_lettered_at IS NOT NULL)"
            ")",
            name="ck_flow_run_webhook_deliveries_delivery_timestamps",
        ),
        CheckConstraint(
            "("
            "(claim_token IS NULL AND claimed_at IS NULL AND claim_expires_at IS NULL) "
            "OR "
            "(delivery_status = 'pending' "
            "AND claim_token IS NOT NULL "
            "AND claimed_at IS NOT NULL "
            "AND claim_expires_at IS NOT NULL)"
            ")",
            name="ck_flow_run_webhook_deliveries_claim_shape",
        ),
        Index(
            "ix_flow_run_webhook_deliveries_tenant_created",
            "tenant_id",
            "created_at",
        ),
        Index(
            "ix_flow_run_webhook_deliveries_pending_delivery",
            "next_delivery_at",
            "created_at",
            postgresql_where=sa.text("delivery_status = 'pending'"),
        ),
        Index(
            "ix_flow_run_webhook_deliveries_pending_run_tenant",
            "flow_run_id",
            "tenant_id",
            postgresql_where=sa.text("delivery_status = 'pending'"),
        ),
        Index(
            "ix_flow_run_webhook_deliveries_dead_lettered",
            "dead_lettered_at",
            postgresql_where=sa.text("delivery_status = 'dead_lettered'"),
        ),
    )


BUILDER_SESSION_STATUS_VALUES = (
    "chatting",
    "awaiting_approval",
    "applied",
    "cancelled",
)
BUILDER_PLAN_STATUS_VALUES = (
    "proposed",
    "approved",
    "applied",
    "superseded",
)
BUILDER_TARGET_KIND_VALUES = ("create", "edit")
BUILDER_TURN_STATE_VALUES = (
    "open",
    "processing",
    "committed",
    "failed_before_provider",
    "provider_outcome_unknown",
)


class BuilderSessions(BasePublic):
    """Stores Flow AI Builder conversations. Writer: Flow AI Builder session service. Purpose: keep builder chat, planning state, locks, and target Flow linkage."""

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    space_id: Mapped[UUID] = mapped_column(
        ForeignKey(Spaces.id, ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    flow_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Flows.id, ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    target_kind: Mapped[str] = mapped_column(
        sa.String(16),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        sa.String(32),
        nullable=False,
        server_default="chatting",
    )
    actor_user_id: Mapped[UUID] = mapped_column(
        ForeignKey(Users.id, ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    conversation: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        server_default="[]",
    )
    active_request_id: Mapped[Optional[UUID]] = mapped_column(nullable=True)
    lock_token: Mapped[Optional[UUID]] = mapped_column(nullable=True)
    locked_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
    )
    lock_expires_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    latest_plan_id: Mapped[Optional[UUID]] = mapped_column(nullable=True)
    planning_state_jsonb: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
    )
    planning_state_version: Mapped[int] = mapped_column(
        sa.BigInteger,
        nullable=False,
        server_default="0",
    )
    latest_turn_id: Mapped[Optional[UUID]] = mapped_column(nullable=True)
    latest_turn_request_fingerprint: Mapped[Optional[str]] = mapped_column(
        sa.String(64),
        nullable=True,
    )
    latest_turn_request_jsonb: Mapped[Optional[dict[str, object]]] = mapped_column(
        JSONB,
        nullable=True,
    )
    latest_turn_state: Mapped[Optional[str]] = mapped_column(
        sa.String(32),
        nullable=True,
    )
    latest_turn_message_id: Mapped[Optional[UUID]] = mapped_column(nullable=True)
    latest_turn_error_jsonb: Mapped[Optional[dict[str, object]]] = mapped_column(
        JSONB(none_as_null=True),
        nullable=True,
    )

    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_builder_sessions_id_tenant_id"),
        Index(
            "ix_builder_sessions_tenant_actor_updated",
            "tenant_id",
            "actor_user_id",
            "updated_at",
            "created_at",
        ),
        ForeignKeyConstraint(
            ["flow_id", "tenant_id"],
            ["flows.id", "flows.tenant_id"],
            ondelete="CASCADE",
            name="fk_builder_sessions_flow_tenant",
        ),
        ForeignKeyConstraint(
            ["latest_plan_id", "id"],
            ["builder_plans.id", "builder_plans.session_id"],
            name="fk_builder_sessions_latest_plan_session",
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint(
            f"target_kind IN ({','.join(repr(v) for v in BUILDER_TARGET_KIND_VALUES)})",
            name="ck_builder_sessions_target_kind",
        ),
        CheckConstraint(
            f"status IN ({','.join(repr(v) for v in BUILDER_SESSION_STATUS_VALUES)})",
            name="ck_builder_sessions_status",
        ),
        CheckConstraint(
            "("
            "active_request_id IS NULL "
            "AND lock_token IS NULL "
            "AND locked_at IS NULL "
            "AND lock_expires_at IS NULL"
            ") OR ("
            "active_request_id IS NOT NULL "
            "AND lock_token IS NOT NULL "
            "AND locked_at IS NOT NULL "
            "AND lock_expires_at IS NOT NULL"
            ")",
            name="ck_builder_sessions_send_lock_all_or_none",
        ),
        CheckConstraint(
            "(latest_turn_id IS NULL "
            "AND latest_turn_request_fingerprint IS NULL "
            "AND latest_turn_request_jsonb IS NULL "
            "AND latest_turn_state IS NULL "
            "AND latest_turn_message_id IS NULL "
            "AND latest_turn_error_jsonb IS NULL) "
            "OR (latest_turn_id IS NOT NULL "
            "AND latest_turn_request_fingerprint IS NOT NULL "
            "AND latest_turn_request_jsonb IS NOT NULL "
            "AND latest_turn_state IS NOT NULL "
            "AND latest_turn_message_id IS NOT NULL)",
            name="ck_builder_sessions_latest_turn_all_or_none",
        ),
        CheckConstraint(
            "latest_turn_error_jsonb IS NULL OR latest_turn_state = 'committed'",
            name="ck_builder_sessions_latest_turn_error_committed",
        ),
        CheckConstraint(
            "latest_turn_state IS NULL OR "
            f"latest_turn_state IN ({','.join(repr(v) for v in BUILDER_TURN_STATE_VALUES)})",
            name="ck_builder_sessions_latest_turn_state",
        ),
        CheckConstraint(
            "latest_turn_request_fingerprint IS NULL "
            "OR char_length(latest_turn_request_fingerprint) = 64",
            name="ck_builder_sessions_latest_turn_fingerprint_length",
        ),
    )


class BuilderSessionFiles(BaseCrossReference):
    """Stores files attached to Flow AI Builder sessions. Writer: Flow AI Builder session service. Purpose: keep uploaded builder context files tenant-scoped."""

    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("builder_sessions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    file_id: Mapped[UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["session_id", "tenant_id"],
            ["builder_sessions.id", "builder_sessions.tenant_id"],
            ondelete="CASCADE",
            name="fk_builder_session_files_session_tenant",
        ),
        ForeignKeyConstraint(
            ["file_id", "tenant_id"],
            ["files.id", "files.tenant_id"],
            ondelete="CASCADE",
            name="fk_builder_session_files_file_tenant",
        ),
        Index("ix_builder_session_files_file_id", "file_id"),
    )


class BuilderPlans(BasePublic):
    """Stores Flow AI Builder proposed plans. Writer: Flow AI Builder planner. Purpose: preserve one canonical proposal snapshot."""

    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("builder_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        sa.String(32),
        nullable=False,
        server_default="proposed",
    )
    proposal_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        comment="Serialized FlowBuilderProposal.",
    )
    spec_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False)

    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_builder_plans_id_tenant_id"),
        UniqueConstraint("id", "session_id", name="uq_builder_plans_id_session_id"),
        ForeignKeyConstraint(
            ["session_id", "tenant_id"],
            ["builder_sessions.id", "builder_sessions.tenant_id"],
            ondelete="CASCADE",
            name="fk_builder_plans_session_tenant",
        ),
        CheckConstraint(
            f"status IN ({','.join(repr(v) for v in BUILDER_PLAN_STATUS_VALUES)})",
            name="ck_builder_plans_status",
        ),
    )
