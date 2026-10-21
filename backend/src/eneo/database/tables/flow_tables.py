"""Tables for flows and their runs.

Value vocabularies are literal tuples here so the table module never imports
domain code (develop's tables all follow that rule). The domain enums in
``eneo.flows`` mirror these strings.
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import TIMESTAMP, ForeignKey, Index, UniqueConstraint, func
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from eneo.database.tables.api_keys_v2_table import ApiKeysV2
from eneo.database.tables.base_class import BasePublic, BaseWithTableName
from eneo.database.tables.files_table import Files, file_usage
from eneo.database.tables.job_table import Jobs
from eneo.database.tables.sessions_table import Sessions
from eneo.database.tables.spaces_table import Spaces
from eneo.database.tables.tenant_table import Tenants
from eneo.database.tables.users_table import Users
from eneo.files.file_models import FileUsageKind

FLOW_RUN_STATUSES = (
    "queued",
    "running",
    "awaiting_review",
    "completed",
    "failed",
    "cancelled",
)
FLOW_STEP_RESULT_STATUSES = (
    "pending",
    "running",
    "awaiting_review",
    "completed",
    "failed",
    "cancelled",
    "skipped",
)
FLOW_STEP_ATTEMPT_STATUSES = ("started", "completed", "failed", "outcome_unknown")
FLOW_REVIEW_CHECKPOINT_STATES = (
    "awaiting_review",
    "edited",
    "approved",
    "rejected",
    "resumed",
    "cancelled",
    "expired",
)
# States in which a checkpoint still blocks or owns its run; at most one per run.
FLOW_REVIEW_CHECKPOINT_ACTIVE_STATES = ("awaiting_review", "edited", "approved")
FLOW_PRINCIPAL_TYPES = ("user", "service")
FLOW_FILE_ROLES = ("template", "runtime_upload")
FLOW_REVISION_CHANNELS = ("mcp", "api")
FLOW_RUN_FILE_ROLES = ("input", "output")


class Flows(BasePublic):
    name: Mapped[str] = mapped_column()
    description: Mapped[Optional[str]] = mapped_column()
    # The draft definition (eneo.flows.definition.FlowDefinition as JSON).
    definition: Mapped[dict[str, object]] = mapped_column(JSONB)
    # Points at flow_versions.version; NULL means never published.
    published_version: Mapped[Optional[int]] = mapped_column()
    deleted_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey(Tenants.id, ondelete="CASCADE"))
    space_id: Mapped[UUID] = mapped_column(ForeignKey(Spaces.id, ondelete="CASCADE"))
    user_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Users.id, ondelete="SET NULL")
    )
    # The chat the flow was authored in; the flow page reopens it.
    conversation_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Sessions.id, ondelete="SET NULL")
    )

    __table_args__ = (Index("ix_flows_tenant_space", "tenant_id", "space_id"),)


class FlowVersions(BasePublic):
    version: Mapped[int] = mapped_column()
    # Immutable snapshot a run executes; the draft is never read by a run.
    definition: Mapped[dict[str, object]] = mapped_column(JSONB)
    runtime_bindings: Mapped[Optional[dict[str, object]]] = mapped_column(JSONB)
    # The flow_revisions.revision this version froze; NULL for versions
    # published before revisions were kept.
    revision: Mapped[Optional[int]] = mapped_column()

    flow_id: Mapped[UUID] = mapped_column(ForeignKey(Flows.id, ondelete="CASCADE"))
    published_by_user_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Users.id, ondelete="SET NULL")
    )

    __table_args__ = (
        UniqueConstraint("flow_id", "version", name="uq_flow_versions_flow_version"),
    )


class FlowRevisions(BasePublic):
    """One saved state of a flow's name, description and definition.

    Written on create and on every change; never updated or deleted on its
    own (a flow's history goes with the flow). Restoring one writes a new
    revision rather than rewinding the numbering.
    """

    revision: Mapped[int] = mapped_column()
    name: Mapped[str] = mapped_column()
    description: Mapped[Optional[str]] = mapped_column()
    definition: Mapped[dict[str, object]] = mapped_column(JSONB)
    principal_type: Mapped[str] = mapped_column(server_default=sa_text("'user'"))
    principal_user_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Users.id, ondelete="SET NULL")
    )
    principal_service_id: Mapped[Optional[UUID]] = mapped_column()
    # 'mcp' (the flows chat) | 'api' (REST, including a restore from the panel)
    channel: Mapped[str] = mapped_column(server_default=sa_text("'api'"))
    # One line the author gave on what changed and why.
    note: Mapped[Optional[str]] = mapped_column()

    flow_id: Mapped[UUID] = mapped_column(ForeignKey(Flows.id, ondelete="CASCADE"))

    __table_args__ = (
        UniqueConstraint("flow_id", "revision", name="uq_flow_revisions_flow_revision"),
    )


class FlowEditSessions(BaseWithTableName):
    """A user's edit mode on a flow: one row per flow and user, from the
    moment they enter until they leave. Rows never expire; a deleted flow
    takes them along."""

    flow_id: Mapped[UUID] = mapped_column(
        ForeignKey(Flows.id, ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey(Users.id, ondelete="CASCADE"), primary_key=True
    )
    started_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )


class FlowFiles(BasePublic):
    """Files a flow holds: document templates and uploads awaiting a run."""

    # 'template' | 'runtime_upload'
    role: Mapped[str] = mapped_column()
    step_id: Mapped[Optional[UUID]] = mapped_column()
    principal_type: Mapped[str] = mapped_column(server_default=sa_text("'user'"))
    principal_user_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Users.id, ondelete="SET NULL")
    )
    principal_service_id: Mapped[Optional[UUID]] = mapped_column()

    flow_id: Mapped[UUID] = mapped_column(ForeignKey(Flows.id, ondelete="CASCADE"))
    file_id: Mapped[UUID] = mapped_column(
        ForeignKey(Files.id, ondelete="CASCADE"),
        info=file_usage(FileUsageKind.FLOW_FILE),
    )

    __table_args__ = (
        UniqueConstraint(
            "flow_id", "file_id", "role", name="uq_flow_files_flow_file_role"
        ),
    )


class FlowRuns(BasePublic):
    # The published version the run executes; NULL for a test run of the draft.
    flow_version: Mapped[Optional[int]] = mapped_column()
    runtime_bindings: Mapped[Optional[dict[str, object]]] = mapped_column(JSONB)
    # The definition the run executes, frozen when it was started.
    definition: Mapped[Optional[dict[str, object]]] = mapped_column(JSONB)
    # A test run of the draft: started by an editor without publishing.
    is_test: Mapped[bool] = mapped_column(server_default=sa_text("false"))
    # 'user' | 'service'. A service principal is an API key with no users row.
    principal_type: Mapped[str] = mapped_column(server_default=sa_text("'user'"))
    principal_user_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Users.id, ondelete="SET NULL")
    )
    principal_service_id: Mapped[Optional[UUID]] = mapped_column()
    created_by_api_key_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(ApiKeysV2.id, ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column()
    run_label: Mapped[Optional[str]] = mapped_column()
    idempotency_key: Mapped[Optional[str]] = mapped_column()
    # Form values keyed by field key; files go through flow_run_files.
    input_payload_json: Mapped[Optional[dict[str, object]]] = mapped_column(JSONB)
    # The last step's output (text / value / file ids).
    output_payload_json: Mapped[Optional[dict[str, object]]] = mapped_column(JSONB)
    # {"code": ..., "message": ...}
    error_json: Mapped[Optional[dict[str, object]]] = mapped_column(JSONB)
    started_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    finished_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    # Refreshed by the executing worker; silence means the worker is gone.
    heartbeat_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey(Tenants.id, ondelete="CASCADE"))
    flow_id: Mapped[UUID] = mapped_column(ForeignKey(Flows.id, ondelete="CASCADE"))
    job_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Jobs.id, ondelete="SET NULL")
    )

    step_results: Mapped[list["FlowStepResults"]] = relationship(
        order_by="FlowStepResults.step_order", viewonly=True
    )
    files: Mapped[list["FlowRunFiles"]] = relationship(
        order_by="FlowRunFiles.ordinal", viewonly=True
    )

    __table_args__ = (
        Index("ix_flow_runs_flow_created", "flow_id", "created_at"),
        Index(
            "ix_flow_runs_running",
            "heartbeat_at",
            postgresql_where=sa_text("status = 'running'"),
        ),
        Index(
            "uq_flow_runs_user_idempotency",
            "flow_id",
            "principal_user_id",
            "idempotency_key",
            unique=True,
            postgresql_where=sa_text(
                "principal_user_id IS NOT NULL AND idempotency_key IS NOT NULL"
            ),
        ),
        Index(
            "uq_flow_runs_service_idempotency",
            "flow_id",
            "principal_service_id",
            "idempotency_key",
            unique=True,
            postgresql_where=sa_text(
                "principal_service_id IS NOT NULL AND idempotency_key IS NOT NULL"
            ),
        ),
    )


class FlowRunFiles(BasePublic):
    """Inputs given to a run and outputs it produced."""

    # 'input' | 'output'
    role: Mapped[str] = mapped_column()
    # Input: the form field key; output: null.
    field_key: Mapped[Optional[str]] = mapped_column()
    step_id: Mapped[Optional[UUID]] = mapped_column()
    ordinal: Mapped[int] = mapped_column(server_default=sa_text("0"))

    flow_run_id: Mapped[UUID] = mapped_column(
        ForeignKey(FlowRuns.id, ondelete="CASCADE")
    )
    file_id: Mapped[UUID] = mapped_column(
        ForeignKey(Files.id, ondelete="CASCADE"),
        info=file_usage(FileUsageKind.FLOW_RUN_FILE),
    )

    __table_args__ = (
        UniqueConstraint(
            "flow_run_id", "file_id", "role", name="uq_flow_run_files_run_file_role"
        ),
    )


class FlowStepResults(BasePublic):
    # Step identity from the published definition, not a FK to the draft.
    step_id: Mapped[UUID] = mapped_column()
    step_order: Mapped[int] = mapped_column()
    status: Mapped[str] = mapped_column()
    current_attempt_no: Mapped[int] = mapped_column(server_default=sa_text("0"))
    # What the step read (rendered input; a transcript's segments live here as
    # input_payload_json.transcription, where the run API exposes them).
    input_payload_json: Mapped[Optional[dict[str, object]]] = mapped_column(JSONB)
    # {"text": ..., "value": ..., "file_ids": [...]}
    output_payload_json: Mapped[Optional[dict[str, object]]] = mapped_column(JSONB)
    num_tokens_input: Mapped[Optional[int]] = mapped_column()
    num_tokens_output: Mapped[Optional[int]] = mapped_column()
    error_code: Mapped[Optional[str]] = mapped_column()
    error_message: Mapped[Optional[str]] = mapped_column()
    started_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    finished_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))

    flow_run_id: Mapped[UUID] = mapped_column(
        ForeignKey(FlowRuns.id, ondelete="CASCADE")
    )

    __table_args__ = (
        UniqueConstraint(
            "flow_run_id", "step_id", name="uq_flow_step_results_run_step"
        ),
    )


class FlowStepAttempts(BasePublic):
    step_id: Mapped[UUID] = mapped_column()
    attempt_no: Mapped[int] = mapped_column()
    # started | completed | failed | outcome_unknown. A crash between the
    # claim and the outcome commit leaves 'started'; recovery marks it
    # outcome_unknown and the provider call is never repeated.
    status: Mapped[str] = mapped_column(server_default=sa_text("'started'"))
    error_message: Mapped[Optional[str]] = mapped_column()
    finished_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))

    flow_run_id: Mapped[UUID] = mapped_column(
        ForeignKey(FlowRuns.id, ondelete="CASCADE")
    )

    __table_args__ = (
        UniqueConstraint(
            "flow_run_id",
            "step_id",
            "attempt_no",
            name="uq_flow_step_attempts_run_step_attempt",
        ),
        Index(
            "ix_flow_step_attempts_run_started",
            "flow_run_id",
            postgresql_where=sa_text("status = 'started'"),
        ),
    )


class FlowRunReviewCheckpoints(BasePublic):
    step_id: Mapped[UUID] = mapped_column()
    step_order: Mapped[int] = mapped_column()
    attempt_no: Mapped[int] = mapped_column(server_default=sa_text("1"))
    state: Mapped[str] = mapped_column(server_default=sa_text("'awaiting_review'"))
    # Bumped on every edit; clients send expected_checkpoint_revision.
    revision: Mapped[int] = mapped_column(server_default=sa_text("1"))
    # 'view' | 'edit'
    review_mode: Mapped[str] = mapped_column()
    # 'text' | 'json'
    output_type: Mapped[str] = mapped_column(server_default=sa_text("'text'"))
    original_payload_json: Mapped[Optional[dict[str, object]]] = mapped_column(JSONB)
    current_payload_json: Mapped[Optional[dict[str, object]]] = mapped_column(JSONB)
    requester_principal_type: Mapped[str] = mapped_column(
        server_default=sa_text("'user'")
    )
    requester_user_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Users.id, ondelete="SET NULL")
    )
    requester_service_id: Mapped[Optional[UUID]] = mapped_column()
    decided_by_principal_type: Mapped[Optional[str]] = mapped_column()
    decided_by_user_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Users.id, ondelete="SET NULL")
    )
    decided_by_service_id: Mapped[Optional[UUID]] = mapped_column()
    reason: Mapped[Optional[str]] = mapped_column()
    edited_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    approved_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    rejected_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    resumed_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    expires_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey(Tenants.id, ondelete="CASCADE"))
    flow_id: Mapped[UUID] = mapped_column(ForeignKey(Flows.id, ondelete="CASCADE"))
    flow_run_id: Mapped[UUID] = mapped_column(
        ForeignKey(FlowRuns.id, ondelete="CASCADE")
    )

    __table_args__ = (
        Index(
            "uq_flow_run_review_checkpoints_one_active_per_run",
            "flow_run_id",
            unique=True,
            postgresql_where=sa_text(
                "state IN ('awaiting_review', 'edited', 'approved')"
            ),
        ),
    )


class FlowTranscriptCorrections(BasePublic):
    """Non-destructive corrections anchored to a transcribe step's segments."""

    step_id: Mapped[UUID] = mapped_column()
    revision: Mapped[int] = mapped_column(server_default=sa_text("1"))
    schema_version: Mapped[int] = mapped_column(server_default=sa_text("3"))
    segments_hash: Mapped[str] = mapped_column()
    occurrences_json: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, server_default=sa_text("'[]'::jsonb")
    )
    speaker_edits_json: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, server_default=sa_text("'[]'::jsonb")
    )
    speaker_names: Mapped[Optional[dict[str, object]]] = mapped_column(JSONB)
    edited_by_principal_type: Mapped[str] = mapped_column(
        server_default=sa_text("'user'")
    )
    edited_by_user_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Users.id, ondelete="SET NULL")
    )
    edited_by_service_id: Mapped[Optional[UUID]] = mapped_column()

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey(Tenants.id, ondelete="CASCADE"))
    flow_id: Mapped[UUID] = mapped_column(ForeignKey(Flows.id, ondelete="CASCADE"))
    flow_run_id: Mapped[UUID] = mapped_column(
        ForeignKey(FlowRuns.id, ondelete="CASCADE")
    )

    __table_args__ = (
        UniqueConstraint(
            "flow_run_id", "step_id", name="uq_flow_transcript_corrections_run_step"
        ),
    )
