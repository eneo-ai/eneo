from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from intric.main.models import NOT_PROVIDED, NotProvided, partial_model


class FlowInputSource(str, Enum):
    FLOW_INPUT = "flow_input"
    PREVIOUS_STEP = "previous_step"
    ALL_PREVIOUS_STEPS = "all_previous_steps"
    HTTP_GET = "http_get"
    HTTP_POST = "http_post"


class FlowInputType(str, Enum):
    TEXT = "text"
    JSON = "json"
    IMAGE = "image"
    AUDIO = "audio"
    DOCUMENT = "document"
    FILE = "file"
    ANY = "any"


class FlowOutputType(str, Enum):
    TEXT = "text"
    JSON = "json"
    PDF = "pdf"
    DOCX = "docx"


class FlowOutputMode(str, Enum):
    PASS_THROUGH = "pass_through"
    HTTP_POST = "http_post"
    TRANSCRIBE_ONLY = "transcribe_only"


class FlowMcpPolicy(str, Enum):
    INHERIT = "inherit"
    RESTRICTED = "restricted"


class FlowStepCreateRequest(BaseModel):
    assistant_id: UUID
    step_order: int
    user_description: str | None = None
    input_source: str
    input_type: str
    input_contract: dict[str, Any] | None = None
    output_mode: str
    output_type: str
    output_contract: dict[str, Any] | None = None
    input_bindings: dict[str, Any] | None = None
    output_classification_override: int | None = None
    mcp_policy: str
    input_config: dict[str, Any] | None = None
    output_config: dict[str, Any] | None = None


class FlowCreateRequest(BaseModel):
    space_id: UUID
    name: str
    description: str | None = None
    steps: list[FlowStepCreateRequest]
    metadata_json: dict[str, Any] | None = None
    data_retention_days: int | None = None


@partial_model
class FlowUpdateRequest(BaseModel):
    name: str
    description: str | None
    steps: list[FlowStepCreateRequest]
    metadata_json: dict[str, Any] | None | NotProvided = Field(default=NOT_PROVIDED)
    data_retention_days: int | None | NotProvided = Field(default=NOT_PROVIDED)


class FlowStepPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID | None = None
    assistant_id: UUID
    step_order: int
    user_description: str | None = None
    input_source: str
    input_type: str
    input_contract: dict[str, Any] | None = None
    output_mode: str
    output_type: str
    output_contract: dict[str, Any] | None = None
    input_bindings: dict[str, Any] | None = None
    output_classification_override: int | None = None
    mcp_policy: str
    input_config: dict[str, Any] | None = None
    output_config: dict[str, Any] | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class FlowSparsePublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID | None = None
    tenant_id: UUID
    space_id: UUID
    name: str
    description: str | None = None
    created_by_user_id: UUID | None = None
    owner_user_id: UUID | None = None
    published_version: int | None = None
    metadata_json: dict[str, Any] | None = None
    data_retention_days: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class FlowPublic(FlowSparsePublic):
    steps: list[FlowStepPublic]


class FlowRunCreateRequest(BaseModel):
    input_payload_json: dict[str, Any] | None = None
    file_ids: list[UUID] | None = None


class FlowAssistantCreateRequest(BaseModel):
    name: str


class FlowRunPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    flow_id: UUID
    flow_version: int
    user_id: UUID | None = None
    tenant_id: UUID
    status: str
    cancelled_at: datetime | None = None
    input_payload_json: dict[str, Any] | None = None
    output_payload_json: dict[str, Any] | None = None
    error_message: str | None = None
    job_id: UUID | None = None
    created_at: datetime
    updated_at: datetime


class FlowInputPolicyPublic(BaseModel):
    flow_id: UUID
    input_type: str | None = None
    input_source: str | None = None
    accepts_file_upload: bool
    accepted_mimetypes: list[str] = Field(default_factory=list)
    max_file_size_bytes: int | None = None
    max_files_per_run: int | None = None
    recommended_run_payload: dict[str, Any] | None = None


class FlowRunStepPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID | None = None
    step_id: UUID | None = None
    step_order: int
    assistant_id: UUID | None = None
    status: str
    input_payload_json: dict[str, Any] | None = None
    output_payload_json: dict[str, Any] | None = None
    num_tokens_input: int | None = None
    num_tokens_output: int | None = None
    error_message: str | None = None
    diagnostics: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class FlowRunRedispatchResponse(BaseModel):
    run: FlowRunPublic
    redispatched_count: int


class GraphResponse(BaseModel):
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]


class FlowRunDebugIoTypes(BaseModel):
    input: str | None = None
    output: str | None = None


class FlowRunDebugInput(BaseModel):
    source: str | None = None
    type: str | None = None
    contract: dict[str, Any] | None = None
    bindings: dict[str, Any] | None = None
    config: dict[str, Any] | None = None


class FlowRunDebugOutput(BaseModel):
    mode: str | None = None
    type: str | None = None
    contract: dict[str, Any] | None = None
    classification: int | None = None
    config: dict[str, Any] | None = None


class FlowRunDebugMcp(BaseModel):
    policy: str | None = None
    tool_allowlist: list[str] = Field(default_factory=list)


class FlowRunDebugRagReferenceChunk(BaseModel):
    chunk_no: int = 0
    score: float = 0.0
    snippet: str = ""


class FlowRunDebugRagReference(BaseModel):
    id: str
    id_short: str
    title: str | None = None
    hit_count: int = 0
    best_score: float = 0.0
    chunks: list[FlowRunDebugRagReferenceChunk] = Field(default_factory=list)


class FlowRunDebugRag(BaseModel):
    attempted: bool | None = None
    status: str | None = None
    version: int | None = None
    timeout_seconds: int | None = None
    include_info_blobs: bool | None = None
    chunks_retrieved: int | None = None
    raw_chunks_count: int | None = None
    deduped_chunks_count: int | None = None
    unique_sources: int | None = None
    source_ids: list[str] | None = None
    source_ids_short: list[str] | None = None
    error_code: str | None = None
    retrieval_duration_ms: int | None = None
    retrieval_error_type: str | None = None
    references: list[FlowRunDebugRagReference] | None = None
    references_truncated: bool | None = None


class FlowRunDebugStep(BaseModel):
    step_id: str | None = None
    step_order: int | None = None
    assistant_id: str | None = None
    io_types: FlowRunDebugIoTypes
    input: FlowRunDebugInput
    output: FlowRunDebugOutput
    mcp: FlowRunDebugMcp
    rag: FlowRunDebugRag | None = None


class FlowRunDebugRun(BaseModel):
    run_id: str
    flow_id: str
    flow_version: int
    status: str


class FlowRunDebugDefinition(BaseModel):
    flow_id: str
    version: int
    checksum: str
    steps_count: int


class FlowRunDebugSecurity(BaseModel):
    redaction_applied: bool
    classification_field: str
    mcp_policy_field: str


class FlowRunDebugExport(BaseModel):
    schema_version: str
    generated_at: datetime
    run: FlowRunDebugRun
    definition: FlowRunDebugDefinition
    definition_snapshot: dict[str, Any]
    steps: list[FlowRunDebugStep]
    security: FlowRunDebugSecurity


class FlowRunEvidenceResponse(BaseModel):
    run: dict[str, Any]
    definition_snapshot: dict[str, Any]
    step_results: list[dict[str, Any]]
    step_attempts: list[dict[str, Any]]
    debug_export: FlowRunDebugExport
