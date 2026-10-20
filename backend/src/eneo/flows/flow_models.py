"""Public models for flows: what the REST API and the MCP tools return.

The run-side shapes follow the names the previous flows API used
(``FlowRunSummaryPublic``, ``FlowRunStepPublic``,
``FlowRunReviewCheckpointPublic``, ``FlowTranscriptCorrectionsPublic``) so
API consumers keep working. The authoring side is new: a flow is one
:class:`~eneo.flows.definition.FlowDefinition`.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from eneo.flows.definition import FlowDefinition, FormField, StepKind


class FlowRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_REVIEW = "awaiting_review"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in (
            FlowRunStatus.COMPLETED,
            FlowRunStatus.FAILED,
            FlowRunStatus.CANCELLED,
        )

    @property
    def is_active(self) -> bool:
        return not self.is_terminal


class StepResultStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    AWAITING_REVIEW = "awaiting_review"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


class StepAttemptStatus(StrEnum):
    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"
    OUTCOME_UNKNOWN = "outcome_unknown"


class ReviewCheckpointState(StrEnum):
    AWAITING_REVIEW = "awaiting_review"
    EDITED = "edited"
    APPROVED = "approved"
    REJECTED = "rejected"
    RESUMED = "resumed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class PrincipalType(StrEnum):
    USER = "user"
    SERVICE = "service"


# --- Flows (authoring side) ---


class FlowSparsePublic(BaseModel):
    """A list row."""

    id: UUID
    space_id: UUID
    name: str
    description: Optional[str] = None
    published_version: Optional[int] = None
    step_count: int
    step_kinds: list[StepKind]
    conversation_id: Optional[UUID] = None
    last_run: Optional["FlowRunSummaryPublic"] = None
    created_at: datetime
    updated_at: datetime


class FlowPublic(BaseModel):
    """A flow with its draft definition; what the panel renders."""

    id: UUID
    space_id: UUID
    name: str
    description: Optional[str] = None
    definition: FlowDefinition
    published_version: Optional[int] = None
    # True when the draft differs from the published version (or is unpublished).
    has_unpublished_changes: bool = False
    # The current revision of the draft (see FlowRevisionSummaryPublic).
    revision: int = 1
    conversation_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime


class FlowRevisionChangesPublic(BaseModel):
    """What a revision changed against the one before it."""

    # The first revision: nothing to compare with.
    is_initial: bool = False
    name_changed: bool = False
    description_changed: bool = False
    form_fields_changed: bool = False
    # Step names, in the order of the revision they appear in.
    steps_added: list[str] = Field(default_factory=list[str])
    steps_removed: list[str] = Field(default_factory=list[str])
    steps_changed: list[str] = Field(default_factory=list[str])


class FlowRevisionSummaryPublic(BaseModel):
    """A row in a flow's history: every save, newest first."""

    flow_id: UUID
    revision: int
    name: str
    created_at: datetime
    principal_type: PrincipalType
    created_by_user_id: Optional[UUID] = None
    # "mcp" (the flows chat) | "api"
    channel: str
    note: Optional[str] = None
    # The version a publish froze from this revision, when one did.
    published_version: Optional[int] = None
    changes: FlowRevisionChangesPublic


class FlowRevisionPublic(FlowRevisionSummaryPublic):
    description: Optional[str] = None
    definition: FlowDefinition


class FlowCreateRequest(BaseModel):
    """Start a flow: an empty draft in a space, authored in its chat afterwards."""

    model_config = ConfigDict(extra="forbid")

    space_id: UUID
    name: Optional[str] = Field(default=None, max_length=200)


class FlowConversationBindRequest(BaseModel):
    """Bind the flow to the chat (a flows chat of its space) that authors it."""

    model_config = ConfigDict(extra="forbid")

    session_id: UUID


class FlowAuthoringAssistantPublic(BaseModel):
    """The hidden assistant the flows chat talks to, for one space."""

    assistant_id: UUID
    space_id: UUID


# --- Run contract (what a client needs to start a run) ---


class FlowRunContractStepPublic(BaseModel):
    step_id: UUID
    key: str
    name: str
    kind: StepKind


class FlowFinalOutputContractPublic(BaseModel):
    kind: StepKind
    # "text" | "json" | "docx" | "pdf" | "transcript"
    output_type: str


class FlowRunContractPublic(BaseModel):
    flow_id: UUID
    published_flow_version: int
    form_fields: list[FormField]
    steps_requiring_review: list[FlowRunContractStepPublic]
    final_output: Optional[FlowFinalOutputContractPublic] = None


# --- Runs ---


class FlowRunCreateRequest(BaseModel):
    """Start a run of the published version, or a test run of the draft.

    ``values`` carries text, number and select fields by key; ``files``
    carries file and audio fields by key as ids of files the caller
    uploaded (through the runtime-files endpoint or the chat). ``draft``
    runs the current draft without publishing it: for editors trying a flow
    out while building it; ``expected_flow_version`` does not apply then.
    """

    model_config = ConfigDict(extra="forbid")

    values: dict[str, Any] = Field(default_factory=dict)
    files: dict[str, list[UUID]] = Field(default_factory=dict)
    run_label: Optional[str] = Field(default=None, max_length=200)
    expected_flow_version: Optional[int] = None
    draft: bool = False


class FlowRunErrorPublic(BaseModel):
    code: str
    message: str


class FlowRunFilePublic(BaseModel):
    id: UUID
    name: str
    mimetype: Optional[str] = None
    size: Optional[int] = None
    # "input" | "output"
    role: str
    field_key: Optional[str] = None
    step_id: Optional[UUID] = None


class FlowArtifactPublic(BaseModel):
    """A file a run of the flow produced, listed across runs."""

    file: FlowRunFilePublic
    run_id: UUID
    run_label: Optional[str] = None
    created_at: datetime


class FlowRunSummaryPublic(BaseModel):
    id: UUID
    flow_id: UUID
    # The published version the run executes; null for a test run of the draft.
    flow_version: Optional[int] = None
    # Started on the draft, without publishing, by an editor trying the flow.
    is_test: bool = False
    tenant_id: UUID
    principal_type: PrincipalType
    status: FlowRunStatus
    run_label: Optional[str] = None
    job_id: Optional[UUID] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class FlowRunStepPublic(BaseModel):
    step_id: UUID
    key: str
    name: str
    kind: StepKind
    step_order: int
    status: StepResultStatus
    current_attempt_no: int = 0
    input_payload_json: Optional[dict[str, Any]] = None
    output_payload_json: Optional[dict[str, Any]] = None
    result_files: list[FlowRunFilePublic] = Field(
        default_factory=list[FlowRunFilePublic]
    )
    num_tokens_input: Optional[int] = None
    num_tokens_output: Optional[int] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class FlowRunReviewCheckpointPublic(BaseModel):
    id: UUID
    flow_id: UUID
    flow_run_id: UUID
    step_id: UUID
    step_order: int
    attempt_no: int
    state: ReviewCheckpointState
    revision: int
    # "view" | "edit"
    review_mode: str
    # "text" | "json"
    output_type: str
    original_payload_json: Optional[dict[str, Any]] = None
    current_payload_json: Optional[dict[str, Any]] = None
    requester_principal_type: PrincipalType
    decided_by_principal_type: Optional[PrincipalType] = None
    reason: Optional[str] = None
    edited_at: Optional[datetime] = None
    approved_at: Optional[datetime] = None
    rejected_at: Optional[datetime] = None
    resumed_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class FlowRunPublic(FlowRunSummaryPublic):
    input_payload_json: Optional[dict[str, Any]] = None
    output_payload_json: Optional[dict[str, Any]] = None
    error: Optional[FlowRunErrorPublic] = None
    input_files: list[FlowRunFilePublic] = Field(
        default_factory=list[FlowRunFilePublic]
    )
    result_files: list[FlowRunFilePublic] = Field(
        default_factory=list[FlowRunFilePublic]
    )
    steps: list[FlowRunStepPublic] = Field(default_factory=list[FlowRunStepPublic])
    review_checkpoint: Optional[FlowRunReviewCheckpointPublic] = None


# --- Review checkpoint requests ---


class FlowRunReviewCheckpointEditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_checkpoint_revision: int
    # Text review: {"text": ...}; JSON review: {"value": ...}
    current_payload_json: dict[str, Any]


class FlowRunReviewCheckpointApproveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_checkpoint_revision: int


class FlowRunReviewCheckpointRejectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_checkpoint_revision: int
    reason: Optional[str] = Field(default=None, max_length=2000)


class FlowRunReviewCheckpointResumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_checkpoint_revision: int


class FlowRunReviewCheckpointResumeResponse(BaseModel):
    checkpoint: FlowRunReviewCheckpointPublic
    run: FlowRunSummaryPublic


# --- Transcript corrections (a transcribe step's transcript, corrected on read) ---


class TranscriptCorrectionOccurrencePublic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segment_index: int = Field(ge=0)
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=0)
    original: str
    corrected: str = ""


class TranscriptSpeakerEditPublic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segment_index: int = Field(ge=0)
    char_start: Optional[int] = None
    char_end: Optional[int] = None
    original: Optional[str] = None
    original_speaker: Optional[str] = None
    speaker: Optional[str] = None
    decision: Literal["confirmed", "unresolved"] = "confirmed"


class FlowTranscriptCorrectionsEditRequest(BaseModel):
    """Replace a step's corrections; ``expected_revision`` null creates the row."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = 3
    segments_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_revision: Optional[int] = None
    occurrences: list[TranscriptCorrectionOccurrencePublic] = Field(
        default_factory=list[TranscriptCorrectionOccurrencePublic]
    )
    speaker_edits: list[TranscriptSpeakerEditPublic] = Field(
        default_factory=list[TranscriptSpeakerEditPublic]
    )
    speaker_names: Optional[dict[str, Optional[str]]] = None


class FlowTranscriptCorrectionsPublic(BaseModel):
    schema_version: int
    segments_hash: str
    flow_run_id: UUID
    step_id: UUID
    occurrences: list[TranscriptCorrectionOccurrencePublic]
    speaker_edits: list[TranscriptSpeakerEditPublic]
    speaker_names: dict[str, Optional[str]]
    revision: int
    # The transcript was re-made since these were written; do not apply them.
    stale: bool
    edited_by_principal_type: PrincipalType
    created_at: datetime
    updated_at: datetime


class FlowTranscriptPublic(BaseModel):
    """A transcribe step's transcript with the corrections applied on read."""

    flow_run_id: UUID
    step_id: UUID
    segments_hash: str
    segments: list[dict[str, Any]]
    speaker_names: dict[str, Optional[str]]
    text: str
    corrections_revision: Optional[int] = None


# --- Compact run state, shared by the MCP tools and the panel ---


class FlowRunStateStepPublic(BaseModel):
    step_id: UUID
    key: str
    name: str
    kind: StepKind
    status: StepResultStatus
    # A short, bounded look at the output (first lines of text, file names).
    preview: Optional[str] = None
    error_message: Optional[str] = None


class FlowRunStatePublic(BaseModel):
    """What ``run_flow`` / ``get_run`` return; small enough for a tool result."""

    flow_id: UUID
    run_id: UUID
    flow_version: Optional[int] = None
    is_test: bool = False
    status: FlowRunStatus
    run_label: Optional[str] = None
    steps: list[FlowRunStateStepPublic] = Field(
        default_factory=list[FlowRunStateStepPublic]
    )
    review_checkpoint: Optional[FlowRunReviewCheckpointPublic] = None
    output_files: list[FlowRunFilePublic] = Field(
        default_factory=list[FlowRunFilePublic]
    )
    error: Optional[FlowRunErrorPublic] = None
    created_at: datetime
    updated_at: datetime
