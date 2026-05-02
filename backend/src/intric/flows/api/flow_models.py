from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any, Literal, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from intric.authentication.principal_types import PrincipalType
from intric.flows.enums import (
    FlowInputSource,
    FlowInputType,
    FlowMcpPolicy,
    FlowOutputMode,
    FlowOutputType,
    FlowRunStatus,
    FlowRuntimeInputFormat,
    FlowStepAttemptStatus,
    FlowStepResultStatus,
    FlowTemplateAssetStatus,
)
from intric.flows.flow_run_evidence_export_manifest import EvidenceExportManifest
from intric.flows.flow_run_step_result_file import FlowRunStepResultFile
from intric.main.exceptions import BadRequestException
from intric.main.models import NOT_PROVIDED, NotProvided, partial_model

FLOW_STEP_PUBLIC_EXAMPLE: dict[str, Any] = {
    "id": "00000000-0000-0000-0000-000000000101",
    "assistant_id": "00000000-0000-0000-0000-000000000201",
    "step_order": 1,
    "user_description": "Transcribe uploaded audio into Swedish text.",
    "input_source": "flow_input",
    "input_type": "audio",
    "output_mode": "transcribe_only",
    "output_type": "text",
    "mcp_policy": "inherit",
    "created_at": "2026-03-17T09:30:00Z",
    "updated_at": "2026-03-17T09:30:00Z",
}

FLOW_SPARSE_PUBLIC_EXAMPLE: dict[str, Any] = {
    "id": "00000000-0000-0000-0000-000000000001",
    "tenant_id": "00000000-0000-0000-0000-000000000010",
    "space_id": "00000000-0000-0000-0000-000000000020",
    "name": "Employee Review Summary",
    "description": "Transcribe a review conversation and return a PDF summary.",
    "created_by_user_id": "00000000-0000-0000-0000-000000000030",
    "owner_user_id": "00000000-0000-0000-0000-000000000030",
    "published_version": 3,
    "metadata_json": {"category": "hr"},
    "data_retention_days": 30,
    "created_at": "2026-03-17T09:30:00Z",
    "updated_at": "2026-03-17T10:00:00Z",
}

FLOW_PUBLIC_EXAMPLE: dict[str, Any] = {
    **FLOW_SPARSE_PUBLIC_EXAMPLE,
    "steps": [
        FLOW_STEP_PUBLIC_EXAMPLE,
        {
            "id": "00000000-0000-0000-0000-000000000102",
            "assistant_id": "00000000-0000-0000-0000-000000000202",
            "step_order": 2,
            "user_description": "Summarize the transcription into a PDF for HR follow-up.",
            "input_source": "previous_step",
            "input_type": "text",
            "output_mode": "pass_through",
            "output_type": "pdf",
            "mcp_policy": "inherit",
            "created_at": "2026-03-17T09:30:00Z",
            "updated_at": "2026-03-17T09:30:00Z",
        },
    ],
}

FLOW_RUNTIME_PUBLIC_EXAMPLE: dict[str, Any] = {
    "id": "00000000-0000-0000-0000-000000000001",
    "space_id": "00000000-0000-0000-0000-000000000020",
    "name": "Employee Review Summary",
    "description": "Transcribe a review conversation and return a PDF summary.",
    "published_version": 3,
    "created_at": "2026-03-17T09:30:00Z",
    "updated_at": "2026-03-17T10:00:00Z",
    "runtime_paths": {
        "run_contract": "/api/v1/flows/00000000-0000-0000-0000-000000000001/run-contract/",
        "input_policy": "/api/v1/flows/00000000-0000-0000-0000-000000000001/input-policy/",
        "graph": "/api/v1/flows/00000000-0000-0000-0000-000000000001/graph/",
        "upload_flow_file": "/api/v1/flows/00000000-0000-0000-0000-000000000001/files/",
        "upload_step_runtime_file_template": "/api/v1/flows/00000000-0000-0000-0000-000000000001/steps/{step_id}/runtime-files/",
        "create_run": "/api/v1/flows/00000000-0000-0000-0000-000000000001/runs/",
        "list_runs": "/api/v1/flows/00000000-0000-0000-0000-000000000001/runs/",
        "get_graph_for_run_template": "/api/v1/flows/00000000-0000-0000-0000-000000000001/graph/?run_id={run_id}",
        "get_run_template": "/api/v1/flows/00000000-0000-0000-0000-000000000001/runs/{run_id}/",
        "list_steps_template": "/api/v1/flows/00000000-0000-0000-0000-000000000001/runs/{run_id}/steps/",
        "evidence_template": "/api/v1/flows/00000000-0000-0000-0000-000000000001/runs/{run_id}/evidence/",
        "artifact_signed_url_template": "/api/v1/flows/00000000-0000-0000-0000-000000000001/runs/{run_id}/artifacts/{file_id}/signed-url/",
    },
}

FLOW_RUN_PUBLIC_EXAMPLE: dict[str, Any] = {
    "id": "00000000-0000-0000-0000-000000000301",
    "flow_id": "00000000-0000-0000-0000-000000000001",
    "flow_version": 3,
    "user_id": "00000000-0000-0000-0000-000000000030",
    "tenant_id": "00000000-0000-0000-0000-000000000010",
    "trace_id": "00000000-0000-0000-0000-000000000302",
    "status": "queued",
    "cancelled_at": None,
    "started_at": None,
    "finished_at": None,
    "input_payload_json": {"employee_name": "Alex Example"},
    "output_payload_json": None,
    "result_files": [],
    "error_message": None,
    "job_id": "00000000-0000-0000-0000-000000000401",
    "created_at": "2026-03-17T10:05:00Z",
    "updated_at": "2026-03-17T10:05:00Z",
}

FLOW_RUN_STEP_PUBLIC_EXAMPLE: dict[str, Any] = {
    "id": "00000000-0000-0000-0000-000000000501",
    "step_id": "00000000-0000-0000-0000-000000000101",
    "step_order": 1,
    "assistant_id": "00000000-0000-0000-0000-000000000201",
    "status": "completed",
    "input_payload_json": {
        "diagnostics": [
            {
                "code": "runtime_input_consumed",
                "message": "Uploaded audio file was used.",
            }
        ]
    },
    "output_payload_json": {"text": "Hello and welcome to the annual review..."},
    "result_files": [],
    "num_tokens_input": 0,
    "num_tokens_output": 0,
    "error_message": None,
    "diagnostics": [
        {"code": "runtime_input_consumed", "message": "Uploaded audio file was used."}
    ],
    "started_at": "2026-03-17T10:05:05Z",
    "finished_at": "2026-03-17T10:05:30Z",
    "created_at": "2026-03-17T10:05:05Z",
    "updated_at": "2026-03-17T10:05:30Z",
}

FLOW_TEMPLATE_INSPECTION_PUBLIC_EXAMPLE: dict[str, Any] = {
    "asset_id": "00000000-0000-0000-0000-000000000601",
    "file_id": "00000000-0000-0000-0000-000000000602",
    "file_name": "ibic-template.docx",
    "placeholders": [
        {"name": "brukare_namn", "location": "body", "preview": "{{ brukare_namn }}"},
        {"name": "handlaggare", "location": "header", "preview": "{{ handlaggare }}"},
    ],
    "extracted_text_preview": "IBIC plan template with placeholders.",
    "status": "ready",
}

FLOW_TEMPLATE_ASSET_PUBLIC_EXAMPLE: dict[str, Any] = {
    "id": "00000000-0000-0000-0000-000000000601",
    "flow_id": "00000000-0000-0000-0000-000000000001",
    "file_id": "00000000-0000-0000-0000-000000000602",
    "name": "ibic-template.docx",
    "checksum": "sha256:abc123",
    "mimetype": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "placeholders": ["brukare_namn", "handlaggare"],
    "status": "ready",
    "last_updated_by_name": "Case Worker Admin",
    "can_edit": True,
    "can_download": True,
    "can_select": True,
    "can_inspect": True,
    "created_at": "2026-03-17T09:40:00Z",
    "updated_at": "2026-03-17T09:45:00Z",
}

FLOW_RUN_CONTRACT_PUBLIC_EXAMPLE: dict[str, Any] = {
    "flow_id": "00000000-0000-0000-0000-000000000001",
    "published_flow_version": 3,
    "form_fields": [
        {
            "name": "employee_name",
            "type": "text",
            "label": "Employee name",
            "required": True,
        }
    ],
    "steps_requiring_input": [
        {
            "step_id": "00000000-0000-0000-0000-000000000101",
            "step_order": 1,
            "label": "Upload audio",
            "description": "Provide the recorded review conversation.",
            "required": True,
            "input_format": "audio",
            "max_files": 1,
            "max_file_size_bytes": 52428800,
            "accepted_mimetypes": ["audio/wav", "audio/mpeg"],
        }
    ],
    "aggregate_max_files": 1,
    "template_readiness": [
        {
            "step_id": "00000000-0000-0000-0000-000000000102",
            "template_asset_id": None,
            "template_file_id": None,
            "template_name": None,
            "checksum": None,
            "published_flow_version": 3,
            "status": "unavailable",
            "can_edit": False,
            "can_download": False,
            "message_code": None,
        }
    ],
}

FLOW_RUN_REDISPATCH_RESPONSE_EXAMPLE: dict[str, Any] = {
    "run": FLOW_RUN_PUBLIC_EXAMPLE,
    "redispatched_count": 1,
}

GRAPH_RESPONSE_EXAMPLE: dict[str, Any] = {
    "nodes": [
        {"id": "step-1", "label": "Transcribe uploaded audio", "type": "step"},
        {"id": "step-2", "label": "Create PDF summary", "type": "step"},
    ],
    "edges": [
        {"source": "step-1", "target": "step-2"},
    ],
}


class FlowStepCreateRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "assistant_id": "00000000-0000-0000-0000-000000000001",
                "step_order": 1,
                "user_description": "Transcribe incoming audio",
                "input_source": "flow_input",
                "input_type": "audio",
                "output_mode": "transcribe_only",
                "output_type": "text",
                "mcp_policy": "inherit",
            }
        }
    )

    assistant_id: UUID
    step_order: int
    user_description: str | None = None
    input_source: FlowInputSource
    input_type: FlowInputType
    input_contract: dict[str, Any] | None = None
    output_mode: FlowOutputMode
    output_type: FlowOutputType
    output_contract: dict[str, Any] | None = None
    input_bindings: dict[str, Any] | None = None
    output_classification_override: int | None = None
    mcp_policy: FlowMcpPolicy
    input_config: dict[str, Any] | None = None
    output_config: dict[str, Any] | None = None


class FlowCreateRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "space_id": "00000000-0000-0000-0000-000000000001",
                "name": "Municipality Intake Transcription",
                "description": "Transcribe and summarize citizen audio",
                "steps": [
                    {
                        "assistant_id": "00000000-0000-0000-0000-000000000002",
                        "step_order": 1,
                        "input_source": "flow_input",
                        "input_type": "audio",
                        "output_mode": "transcribe_only",
                        "output_type": "text",
                        "mcp_policy": "inherit",
                    }
                ],
            }
        }
    )

    space_id: UUID
    name: str
    description: str | None = None
    steps: list[FlowStepCreateRequest]
    metadata_json: dict[str, Any] | None = None
    data_retention_days: int | None = None


@partial_model
class FlowUpdateRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "Municipality Intake Transcription v2",
                "description": "Transcribe, redact, and summarize citizen audio submissions.",
                "steps": [
                    {
                        "assistant_id": "00000000-0000-0000-0000-000000000002",
                        "step_order": 1,
                        "user_description": "Transcribe incoming audio",
                        "input_source": "flow_input",
                        "input_type": "audio",
                        "output_mode": "transcribe_only",
                        "output_type": "text",
                        "mcp_policy": "inherit",
                    }
                ],
                "metadata_json": {"category": "municipality-intake"},
                "data_retention_days": 30,
            }
        }
    )

    name: str
    description: str | None
    steps: list[FlowStepCreateRequest]
    metadata_json: dict[str, Any] | None | NotProvided = Field(default=NOT_PROVIDED)
    data_retention_days: int | None | NotProvided = Field(default=NOT_PROVIDED)


class FlowStepPublic(BaseModel):
    model_config = ConfigDict(
        from_attributes=True, json_schema_extra={"example": FLOW_STEP_PUBLIC_EXAMPLE}
    )

    id: UUID | None = None
    assistant_id: UUID
    step_order: int
    user_description: str | None = None
    input_source: FlowInputSource
    input_type: FlowInputType
    input_contract: dict[str, Any] | None = None
    output_mode: FlowOutputMode
    output_type: FlowOutputType
    output_contract: dict[str, Any] | None = None
    input_bindings: dict[str, Any] | None = None
    output_classification_override: int | None = None
    mcp_policy: FlowMcpPolicy
    input_config: dict[str, Any] | None = None
    output_config: dict[str, Any] | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class FlowSparsePublic(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={"example": FLOW_SPARSE_PUBLIC_EXAMPLE},
    )

    id: UUID
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
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={"example": FLOW_PUBLIC_EXAMPLE},
    )

    steps: list[FlowStepPublic]


class FlowRuntimePathsPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    run_contract: str
    input_policy: str
    graph: str
    upload_flow_file: str
    upload_step_runtime_file_template: str
    create_run: str
    list_runs: str
    get_graph_for_run_template: str
    get_run_template: str
    list_steps_template: str
    evidence_template: str
    artifact_signed_url_template: str


class FlowRuntimePublic(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={"example": FLOW_RUNTIME_PUBLIC_EXAMPLE},
    )

    id: UUID
    space_id: UUID
    name: str
    description: str | None = None
    published_version: int
    created_at: datetime | None = None
    updated_at: datetime | None = None
    runtime_paths: FlowRuntimePathsPublic


class StepRunInput(BaseModel):
    file_ids: list[UUID] = Field(default_factory=lambda: cast(list[UUID], []))


class FlowRunCreateRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "expected_flow_version": 7,
                "input_payload_json": {
                    "text": "optional context for downstream prompt steps"
                },
                "step_inputs": {
                    "00000000-0000-0000-0000-000000000003": {
                        "file_ids": ["00000000-0000-0000-0000-000000000004"]
                    }
                },
            }
        }
    )

    expected_flow_version: int | None = None
    input_payload_json: dict[str, Any] | None = None
    step_inputs: dict[UUID, StepRunInput] | None = None

    @model_validator(mode="before")
    @classmethod
    def reject_removed_top_level_file_ids(cls, data: object) -> object:
        if isinstance(data, Mapping) and "file_ids" in data:
            raise BadRequestException(
                "Top-level file_ids is no longer supported. Use step_inputs[step_id].file_ids.",
                code="flow_run_top_level_file_ids_not_supported",
            )
        return cast(object, data)


class FlowAssistantCreateRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": {"name": "Flow Step Assistant"}}
    )

    name: str


class FlowRunPublic(BaseModel):
    model_config = ConfigDict(
        from_attributes=True, json_schema_extra={"example": FLOW_RUN_PUBLIC_EXAMPLE}
    )

    id: UUID
    flow_id: UUID
    flow_version: int
    principal_type: PrincipalType | None = None
    user_id: UUID | None = None
    tenant_id: UUID
    trace_id: UUID
    status: FlowRunStatus
    cancelled_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    input_payload_json: dict[str, Any] | None = None
    output_payload_json: dict[str, Any] | None = None
    result_files: list[FlowRunStepResultFile] = Field(
        default_factory=lambda: cast(list[FlowRunStepResultFile], [])
    )
    error_message: str | None = None
    job_id: UUID | None = None
    created_at: datetime
    updated_at: datetime


class FlowInputPolicyPublic(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "flow_id": "00000000-0000-0000-0000-000000000001",
                "input_type": "audio",
                "input_source": "flow_input",
                "accepts_file_upload": True,
                "accepted_mimetypes": ["audio/wav", "audio/mpeg"],
                "max_file_size_bytes": 52428800,
                "max_files_per_run": 10,
                "recommended_run_payload": {
                    "step_inputs": {
                        "00000000-0000-0000-0000-000000000003": {
                            "file_ids": ["00000000-0000-0000-0000-000000000002"]
                        }
                    }
                },
            }
        }
    )

    flow_id: UUID
    # Keep enum docs for known values while accepting policy strings added server-side.
    input_type: FlowInputType | str | None = None
    input_source: FlowInputSource | str | None = None
    accepts_file_upload: bool
    accepted_mimetypes: list[str] = Field(default_factory=list)
    max_file_size_bytes: int | None = None
    max_files_per_run: int | None = None
    recommended_run_payload: dict[str, Any] | None = None


class FlowRunStepPublic(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={"example": FLOW_RUN_STEP_PUBLIC_EXAMPLE},
    )

    id: UUID | None = None
    flow_run_id: UUID | None = None
    flow_id: UUID | None = None
    tenant_id: UUID | None = None
    step_id: UUID | None = None
    step_order: int
    assistant_id: UUID | None = None
    status: FlowStepResultStatus
    input_payload_json: dict[str, Any] | None = None
    output_payload_json: dict[str, Any] | None = None
    result_files: list[FlowRunStepResultFile] = Field(
        default_factory=lambda: cast(list[FlowRunStepResultFile], [])
    )
    effective_prompt: str | None = None
    model_parameters_json: dict[str, Any] | None = None
    num_tokens_input: int | None = None
    num_tokens_output: int | None = None
    error_message: str | None = None
    flow_step_execution_hash: str | None = None
    diagnostics: list[dict[str, Any]] = Field(
        default_factory=lambda: cast(list[dict[str, Any]], [])
    )
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class FlowRunRedispatchResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": FLOW_RUN_REDISPATCH_RESPONSE_EXAMPLE}
    )

    run: FlowRunPublic
    redispatched_count: int


class GraphNode(BaseModel):
    id: str
    label: str
    type: str
    step_order: int | None = None
    input_source: str | None = None
    input_type: str | None = None
    output_type: str | None = None
    output_mode: str | None = None
    mcp_policy: str | None = None
    output_classification_override: int | None = None
    run_status: str | None = None
    num_tokens_input: int | None = None
    num_tokens_output: int | None = None
    error_message: str | None = None


class GraphEdge(BaseModel):
    source: str
    target: str
    kind: str | None = None
    source_step_order: int | None = None
    target_step_order: int | None = None
    style: str | None = None
    label: str | None = None


class GraphResponse(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": GRAPH_RESPONSE_EXAMPLE})

    nodes: list[GraphNode]
    edges: list[GraphEdge]


class HttpTestRequest(BaseModel):
    config: dict[str, Any]
    direction: Literal["input", "output"] = "output"
    method: str = "POST"
    test_variables: dict[str, Any] | None = None


class HttpTestResponse(BaseModel):
    success: bool
    status_code: int | None = None
    duration_ms: float = 0.0
    response_preview: str | None = None
    request_preview: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None


class FlowTemplatePlaceholderPublic(BaseModel):
    name: str
    location: str
    preview: str | None = None


class FlowTemplateInspectionPublic(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": FLOW_TEMPLATE_INSPECTION_PUBLIC_EXAMPLE}
    )

    asset_id: UUID | None = None
    file_id: UUID
    file_name: str
    placeholders: list[FlowTemplatePlaceholderPublic]
    extracted_text_preview: str | None = None
    status: FlowTemplateAssetStatus | None = None


class FlowTemplateAssetPublic(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={"example": FLOW_TEMPLATE_ASSET_PUBLIC_EXAMPLE},
    )

    id: UUID
    flow_id: UUID
    file_id: UUID
    name: str
    checksum: str
    mimetype: str | None = None
    placeholders: list[str] = Field(default_factory=list)
    status: FlowTemplateAssetStatus
    last_updated_by_name: str | None = None
    can_edit: bool = False
    can_download: bool = False
    can_select: bool = False
    can_inspect: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None


class FlowRuntimeInputContractPublic(BaseModel):
    step_id: UUID
    step_order: int
    label: str | None = None
    description: str | None = None
    required: bool
    input_format: FlowRuntimeInputFormat
    max_files: int | None = None
    max_file_size_bytes: int | None = None
    accepted_mimetypes: list[str] = Field(default_factory=list)


class FlowTemplateReadinessPublic(BaseModel):
    step_id: UUID
    template_asset_id: UUID | None = None
    template_file_id: UUID | None = None
    template_name: str | None = None
    checksum: str | None = None
    published_flow_version: int | None = None
    status: FlowTemplateAssetStatus
    can_edit: bool = False
    can_download: bool = False
    message_code: str | None = None


class FormFieldPublic(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    type: str
    label: str | None = None
    required: bool = False
    options: list[str] | None = None
    order: int | None = None


class FlowRunContractPublic(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": FLOW_RUN_CONTRACT_PUBLIC_EXAMPLE}
    )

    flow_id: UUID
    published_flow_version: int
    form_fields: list[FormFieldPublic] = Field(
        default_factory=lambda: cast(list[FormFieldPublic], [])
    )
    steps_requiring_input: list[FlowRuntimeInputContractPublic] = Field(
        default_factory=lambda: cast(list[FlowRuntimeInputContractPublic], [])
    )
    aggregate_max_files: int | None = None
    template_readiness: list[FlowTemplateReadinessPublic] = Field(
        default_factory=lambda: cast(list[FlowTemplateReadinessPublic], [])
    )


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


class FlowRunDebugMcpServer(BaseModel):
    id: str
    name: str


class FlowRunDebugMcpTool(BaseModel):
    tool_id: str
    server_id: str
    name: str


def _empty_flow_run_debug_mcp_servers() -> list[FlowRunDebugMcpServer]:
    return []


def _empty_flow_run_debug_mcp_tools() -> list[FlowRunDebugMcpTool]:
    return []


class FlowRunDebugMcp(BaseModel):
    policy: str | None = None
    servers: list[FlowRunDebugMcpServer] = Field(
        default_factory=_empty_flow_run_debug_mcp_servers
    )
    tools_enabled: list[FlowRunDebugMcpTool] = Field(
        default_factory=_empty_flow_run_debug_mcp_tools
    )


class FlowRunDebugRagReferenceChunk(BaseModel):
    chunk_no: int = 0
    score: float = 0.0
    snippet: str = ""


class FlowRunDebugRagReference(BaseModel):
    id: str
    id_short: str
    title: str | None = None
    source_title_raw: str | None = None
    display_title: str | None = None
    source_display_name: str | None = None
    source_url: str | None = None
    source_kind: str | None = None
    source_container_kind: str | None = None
    source_container_name: str | None = None
    source_container_name_raw: str | None = None
    source_container_display_name: str | None = None
    source_container_label: str | None = None
    source_container_id: str | None = None
    usage_state: str | None = None
    display_snippet: str | None = None
    display_chunk_no: int | None = None
    display_selection_reason: str | None = None
    quality_flags: list[str] = Field(default_factory=list)
    boilerplate_likelihood: float | None = None
    snippet_quality: str | None = None
    matched_chunk_count: int = 0
    best_score: float = 0.0
    chunks: list[FlowRunDebugRagReferenceChunk] = Field(
        default_factory=lambda: cast(list[FlowRunDebugRagReferenceChunk], [])
    )


class FlowRunDebugRagTracking(BaseModel):
    retrieval_tracked: bool = True
    prompt_context_inclusion_tracked: bool = False
    citation_tracked: bool = False
    material_influence_tracked: bool = False
    selection_basis: str | None = None
    note: str | None = None


class FlowRunDebugRagPromptContextGroup(BaseModel):
    source_id: str | None = None
    source_title: str | None = None
    start_chunk: int | None = None
    end_chunk: int | None = None
    chunk_count: int | None = None
    relevance_score: float | None = None


class FlowRunDebugRagPromptContext(BaseModel):
    tracked: bool = True
    version: int | None = None
    selection_basis: str | None = None
    raw_source_count: int | None = None
    raw_chunk_count: int | None = None
    included_source_count: int | None = None
    not_included_source_count: int | None = None
    included_chunk_count: int | None = None
    knowledge_tokens: int | None = None
    truncated_by_token_budget: bool | None = None
    included_source_ids: list[str] = Field(default_factory=list)
    not_included_source_ids: list[str] = Field(default_factory=list)
    included_source_titles: list[str] = Field(default_factory=list)
    included_source_display_names: list[str] = Field(default_factory=list)
    included_groups: list[FlowRunDebugRagPromptContextGroup] = Field(
        default_factory=lambda: cast(list[FlowRunDebugRagPromptContextGroup], [])
    )
    summary: dict[str, Any] | None = None


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
    source_names: list[str] | None = None
    source_display_names: list[str] | None = None
    has_named_sources: bool | None = None
    tracking: FlowRunDebugRagTracking | None = None
    prompt_context: FlowRunDebugRagPromptContext | None = None


class FlowRunDebugAttempt(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "attempt_no": 1,
                "status": "completed",
                "duration_ms": 5240,
                "requested_model": "gpt-4.1",
                "response_model": "gpt-4.1-mini",
                "provider": "openai",
                "finish_reason": "stop",
                "provider_response_id": "resp_123",
                "num_tokens_input": 321,
                "num_tokens_output": 118,
                "provenance_json": {
                    "llm": {
                        "model_parameters": {
                            "model_name": "gpt-4.1-mini",
                            "provider": "openai",
                            "temperature": None,
                            "reasoning_effort": None,
                            "verbosity": None,
                            "parameter_semantics": {
                                "temperature": {"mode": "model_default"},
                                "top_p": {"mode": "model_default"},
                                "reasoning_effort": {"mode": "model_default"},
                                "verbosity": {"mode": "model_default"},
                            },
                        }
                    }
                },
            }
        }
    )

    attempt_no: int
    status: str | None = None
    duration_ms: int | None = None
    error_code: str | None = None
    requested_model: str | None = None
    response_model: str | None = None
    provider: str | None = None
    finish_reason: str | None = None
    provider_response_id: str | None = None
    num_tokens_input: int | None = None
    num_tokens_output: int | None = None
    provenance_json: dict[str, Any] | None = None


class FlowRunDebugStep(BaseModel):
    step_id: str | None = None
    step_order: int | None = None
    assistant_id: str | None = None
    io_types: FlowRunDebugIoTypes
    input: FlowRunDebugInput
    output: FlowRunDebugOutput
    mcp: FlowRunDebugMcp
    rag: FlowRunDebugRag | None = None
    attempts: list[FlowRunDebugAttempt] = Field(
        default_factory=lambda: cast(list[FlowRunDebugAttempt], [])
    )


class FlowRunDebugRunSummary(BaseModel):
    steps_count: int
    completed_steps: int
    failed_steps: int
    attempts_count: int
    artifacts_count: int
    duration_ms: int | None = None
    models_used: list[str] = Field(default_factory=list)


class FlowRunDebugRun(BaseModel):
    run_id: str
    flow_id: str
    flow_version: int
    trace_id: str | None = None
    status: str
    summary: FlowRunDebugRunSummary | None = None


class FlowRunDebugDefinition(BaseModel):
    flow_id: str
    version: int
    checksum: str
    steps_count: int


class FlowRunDebugSecurity(BaseModel):
    redaction_applied: bool
    classification_field: str
    mcp_policy_field: str
    masked_fields_count: int | None = None


class FlowRunDebugExport(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "schema_version": "eneo.flow.debug-export.v2",
                "generated_at": "2026-03-31T12:00:00Z",
                "run": {
                    "run_id": "a8f5f167-f44f-4d5b-9c06-8ef0db6d7f3b",
                    "flow_id": "f6f2d8fa-2d47-4d08-a7a9-2fef0b37c5ec",
                    "flow_version": 3,
                    "trace_id": "52907745-7678-40a8-9d1c-18af6b1a9fd8",
                    "status": "completed",
                    "summary": {
                        "steps_count": 1,
                        "completed_steps": 1,
                        "failed_steps": 0,
                        "attempts_count": 1,
                        "artifacts_count": 0,
                        "duration_ms": 5240,
                        "models_used": ["gpt-4.1-mini"],
                    },
                },
                "definition": {
                    "flow_id": "f6f2d8fa-2d47-4d08-a7a9-2fef0b37c5ec",
                    "version": 3,
                    "checksum": "sha256:example",
                    "steps_count": 1,
                },
                "definition_snapshot": {"steps": []},
                "steps": [],
                "security": {
                    "redaction_applied": True,
                    "classification_field": "output_classification_override",
                    "mcp_policy_field": "mcp_policy",
                    "masked_fields_count": 2,
                },
            }
        }
    )

    schema_version: str
    generated_at: datetime
    run: FlowRunDebugRun
    definition: FlowRunDebugDefinition
    definition_snapshot: dict[str, Any]
    steps: list[FlowRunDebugStep]
    security: FlowRunDebugSecurity


FLOW_RUN_DEBUG_EXPORT_EXAMPLE: dict[str, Any] = {
    "schema_version": "eneo.flow.debug-export.v2",
    "generated_at": "2026-03-31T12:00:00Z",
    "run": {
        "run_id": "a8f5f167-f44f-4d5b-9c06-8ef0db6d7f3b",
        "flow_id": "f6f2d8fa-2d47-4d08-a7a9-2fef0b37c5ec",
        "flow_version": 3,
        "trace_id": "52907745-7678-40a8-9d1c-18af6b1a9fd8",
        "status": "completed",
        "summary": {
            "steps_count": 1,
            "completed_steps": 1,
            "failed_steps": 0,
            "attempts_count": 1,
            "artifacts_count": 0,
            "duration_ms": 5240,
            "models_used": ["gpt-4.1-mini"],
        },
    },
    "definition": {
        "flow_id": "f6f2d8fa-2d47-4d08-a7a9-2fef0b37c5ec",
        "version": 3,
        "checksum": "sha256:example",
        "steps_count": 1,
    },
    "definition_snapshot": {"steps": []},
    "steps": [],
    "security": {
        "redaction_applied": True,
        "classification_field": "output_classification_override",
        "mcp_policy_field": "mcp_policy",
        "masked_fields_count": 2,
    },
}


FLOW_RUN_RESULT_FILE_EXAMPLE: dict[str, Any] = {
    "flow_run_id": "a8f5f167-f44f-4d5b-9c06-8ef0db6d7f3b",
    "flow_id": "f6f2d8fa-2d47-4d08-a7a9-2fef0b37c5ec",
    "tenant_id": "1f73af48-76fb-4a26-85ee-17f20b722808",
    "step_result_id": "00000000-0000-0000-0000-000000000401",
    "step_id": "00000000-0000-0000-0000-000000000101",
    "step_order": 1,
    "attempt_no": 1,
    "file_id": "00000000-0000-0000-0000-000000000501",
    "ordinal": 0,
    "source": "declared_artifact",
    "name": "case-summary.pdf",
    "checksum": "artifact-checksum",
    "size": 14012,
    "mimetype": "application/pdf",
    "file_type": "document",
    "availability": "available",
}


class FlowStepAttemptPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    flow_run_id: UUID
    flow_id: UUID
    tenant_id: UUID
    step_id: UUID | None = None
    step_order: int
    attempt_no: int
    celery_task_id: str | None = None
    status: FlowStepAttemptStatus
    error_code: str | None = None
    error_message: str | None = None
    requested_model: str | None = None
    response_model: str | None = None
    provider: str | None = None
    finish_reason: str | None = None
    provider_response_id: str | None = None
    num_tokens_input: int | None = None
    num_tokens_output: int | None = None
    provenance_json: dict[str, Any] | None = None
    started_at: datetime
    finished_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class FlowRunEvidenceResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "run": FLOW_RUN_PUBLIC_EXAMPLE,
                "definition_snapshot": {"steps": []},
                "step_results": [FLOW_RUN_STEP_PUBLIC_EXAMPLE],
                "step_attempts": [],
                "result_files": [FLOW_RUN_RESULT_FILE_EXAMPLE],
                "debug_export": FLOW_RUN_DEBUG_EXPORT_EXAMPLE,
            }
        }
    )

    run: FlowRunPublic
    definition_snapshot: dict[str, Any]
    step_results: list[FlowRunStepPublic]
    step_attempts: list[FlowStepAttemptPublic]
    result_files: list[FlowRunStepResultFile]
    debug_export: FlowRunDebugExport


class FlowRunEvidenceExportResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "schema_version": "flow-evidence-export.v3",
                "generated_at": "2026-03-31T12:00:00Z",
                "content_hash": "8f434346648f6b96df89dda901c5176b10a6d83961fca71d1af7bc2f617f4a66",
                "manifest": {
                    "schema_version": "flow-evidence-export.v3",
                    "provenance_schema_version_min": "flow-attempt-provenance.v1",
                    "provenance_schema_version_current": "flow-attempt-provenance.v1",
                    "provenance_persisted_version_status": "not_tracked",
                    "run_id": "a8f5f167-f44f-4d5b-9c06-8ef0db6d7f3b",
                    "tenant_id": "1f73af48-76fb-4a26-85ee-17f20b722808",
                    "flow_id": "f6f2d8fa-2d47-4d08-a7a9-2fef0b37c5ec",
                    "trace_id": "52907745-7678-40a8-9d1c-18af6b1a9fd8",
                    "flow_version": 3,
                    "content_hash": "8f434346648f6b96df89dda901c5176b10a6d83961fca71d1af7bc2f617f4a66",
                    "content_hash_input": "redacted",
                    "exported_at": "2026-03-31T12:00:00Z",
                    "exported_by_user_id": "00000000-0000-0000-0000-000000000030",
                    "export_reason": "support_debug",
                    "detail_mode": "redacted",
                    "redaction_applied": True,
                    "masked_fields_count": 2,
                    "redaction_policy_version": "flow-evidence-redaction.v3",
                    "retention_state_summary": {
                        "tracking_state": "not_tracked",
                        "tombstone_count": 0,
                        "retention_purged_count": 0,
                        "artifact_content_purged_count": 0,
                        "redacted_for_deletion_count": 0,
                        "note": (
                            "No retention tombstones are present in this export; "
                            "rows purged before tombstone tracking remain "
                            "indistinguishable from never-tracked evidence."
                        ),
                    },
                    "artifact_availability_summary": {
                        "tracking_state": "tracked",
                        "artifact_count": 1,
                        "available_count": 1,
                        "content_purged_count": 0,
                        "total_size_bytes": 14012,
                        "artifacts": [FLOW_RUN_RESULT_FILE_EXAMPLE],
                        "note": "Artifact availability is derived from result-file rows joined to file metadata.",
                    },
                },
                "summary": {
                    "status": "completed",
                    "trace_id": "52907745-7678-40a8-9d1c-18af6b1a9fd8",
                    "steps_count": 1,
                    "completed_steps": 1,
                    "failed_steps": 0,
                    "attempts_count": 1,
                    "artifacts_count": 1,
                    "artifact_names": ["case-summary.pdf"],
                    "artifact_details": [
                        {
                            "flow_run_id": "a8f5f167-f44f-4d5b-9c06-8ef0db6d7f3b",
                            "flow_id": "f6f2d8fa-2d47-4d08-a7a9-2fef0b37c5ec",
                            "tenant_id": "1f73af48-76fb-4a26-85ee-17f20b722808",
                            "file_id": "00000000-0000-0000-0000-000000000501",
                            "step_id": "00000000-0000-0000-0000-000000000101",
                            "step_result_id": "00000000-0000-0000-0000-000000000401",
                            "step_order": 1,
                            "attempt_no": 1,
                            "ordinal": 0,
                            "source": "declared_artifact",
                            "name": "case-summary.pdf",
                            "mimetype": "application/pdf",
                            "size": 14012,
                            "checksum": "artifact-checksum",
                            "file_type": "document",
                            "availability": "available",
                        }
                    ],
                    "duration_ms": 5240,
                    "models_used": ["gpt-4.1-mini"],
                    "rag_sources_count": 1,
                    "rag_source_names": ["Municipality policy guide"],
                    "rag_source_display_names": ["Municipality policy guide"],
                    "rag_sources": [
                        {
                            "id": "source-1",
                            "name": "Municipality policy guide",
                            "display_name": "Municipality policy guide",
                            "source_url": "https://example.se/policy-guide",
                            "source_kind": "website",
                            "source_container_kind": "website",
                            "source_container_name": "Municipality knowledge base",
                            "source_container_display_name": "Municipality knowledge base",
                            "source_container_id": "website-1",
                            "usage_state": "inserted_into_prompt",
                        }
                    ],
                    "rag_usage_tracking": {
                        "retrieval_tracked": True,
                        "prompt_context_inclusion_tracked": True,
                        "citation_tracked": False,
                        "material_influence_tracked": False,
                        "selection_basis": "semantic_search_ranked_chunks_grouped_by_source",
                        "note": (
                            "References record retrieved candidates and exact prompt inclusion. "
                            "Citations and material influence are not currently tracked."
                        ),
                    },
                    "citations": {
                        "tracking_mode": "inline_inref_sidecar",
                        "citation_tracked": True,
                        "cited_source_ids": ["source-1"],
                        "cited_source_count": 1,
                        "unknown_citation_ids": [],
                        "uncited_inserted_source_ids": [],
                    },
                    "final_output": {
                        "kind": "mixed",
                        "text_present": True,
                        "text_preview": {
                            "preview": "Decision support generated.",
                            "truncated": False,
                            "byte_size": 27,
                            "sha256": "69c2b1d5990f8f1cd6c9eaf0d6f20bc6f3ddc31a58496a49f4158a709c27a53d",
                        },
                        "structured_present": False,
                        "artifact_count": 1,
                        "artifact_names": ["case-summary.pdf"],
                        "artifact_details": [
                            {
                                "flow_run_id": "a8f5f167-f44f-4d5b-9c06-8ef0db6d7f3b",
                                "flow_id": "f6f2d8fa-2d47-4d08-a7a9-2fef0b37c5ec",
                                "tenant_id": "1f73af48-76fb-4a26-85ee-17f20b722808",
                                "file_id": "00000000-0000-0000-0000-000000000501",
                                "step_id": "00000000-0000-0000-0000-000000000101",
                                "step_result_id": "00000000-0000-0000-0000-000000000401",
                                "step_order": 1,
                                "attempt_no": 1,
                                "ordinal": 0,
                                "source": "declared_artifact",
                                "name": "case-summary.pdf",
                                "mimetype": "application/pdf",
                                "size": 14012,
                                "checksum": "artifact-checksum",
                                "file_type": "document",
                                "availability": "available",
                            }
                        ],
                    },
                    "step_overview": [
                        {
                            "step_order": 1,
                            "step_id": "step-1",
                            "user_description": "Draft the decision support summary",
                            "status": "completed",
                            "attempts_count": 1,
                            "retries": 0,
                            "duration_ms": 5240,
                            "models_used": ["gpt-4.1-mini"],
                            "knowledge_sources_count": 1,
                            "knowledge_usage_state": "inserted_into_prompt",
                            "knowledge_retrieval": {
                                "status": "success",
                                "attempted": True,
                                "retrieval_duration_ms": 182,
                                "unique_sources": 1,
                                "references_truncated": False,
                                "reference_metadata_status": "success",
                                "retrieval_error_type": None,
                                "error_code": None,
                                "source_names": ["Municipality policy guide"],
                                "source_display_names": ["Municipality policy guide"],
                                "prompt_context": {
                                    "tracked": True,
                                    "included_source_count": 1,
                                    "not_included_source_count": 0,
                                    "included_chunk_count": 2,
                                    "knowledge_tokens": 248,
                                    "truncated_by_token_budget": False,
                                    "included_source_ids": ["source-1"],
                                    "included_source_titles": [
                                        "Municipality policy guide"
                                    ],
                                    "included_source_display_names": [
                                        "Municipality policy guide"
                                    ],
                                    "summary": {
                                        "total_sources": 1,
                                        "total_chunks": 2,
                                        "truncated_by_token_budget": False,
                                        "top_ranked_sources": [
                                            {
                                                "source_id": "source-1",
                                                "display_name": "Municipality policy guide",
                                                "source_kind": "website",
                                                "included_group_count": 1,
                                                "included_chunk_count": 2,
                                                "best_score": 0.91,
                                                "rank": 1,
                                            }
                                        ],
                                    },
                                },
                            },
                            "citations": {
                                "tracking_mode": "inline_inref_sidecar",
                                "citation_tracked": True,
                                "cited_source_ids": ["source-1"],
                                "cited_source_count": 1,
                                "unknown_citation_ids": [],
                                "uncited_inserted_source_ids": [],
                            },
                            "artifact_names": ["case-summary.pdf"],
                            "artifact_details": [
                                {
                                    "flow_run_id": "a8f5f167-f44f-4d5b-9c06-8ef0db6d7f3b",
                                    "flow_id": "f6f2d8fa-2d47-4d08-a7a9-2fef0b37c5ec",
                                    "tenant_id": "1f73af48-76fb-4a26-85ee-17f20b722808",
                                    "file_id": "00000000-0000-0000-0000-000000000501",
                                    "step_id": "00000000-0000-0000-0000-000000000101",
                                    "step_result_id": "00000000-0000-0000-0000-000000000401",
                                    "step_order": 1,
                                    "attempt_no": 1,
                                    "ordinal": 0,
                                    "source": "declared_artifact",
                                    "name": "case-summary.pdf",
                                    "mimetype": "application/pdf",
                                    "size": 14012,
                                    "checksum": "artifact-checksum",
                                    "file_type": "document",
                                    "availability": "available",
                                }
                            ],
                            "result_output_kind": "mixed",
                            "output_summary": {
                                "preview": "Decision support generated.",
                                "truncated": False,
                                "byte_size": 27,
                                "sha256": "69c2b1d5990f8f1cd6c9eaf0d6f20bc6f3ddc31a58496a49f4158a709c27a53d",
                            },
                            "input_lineage": {
                                "input_source": "previous_step",
                                "used_question_binding": True,
                                "legacy_prompt_binding_used": False,
                                "uses_runtime_input": True,
                                "runtime_input_format": "document",
                                "runtime_file_count": 1,
                                "runtime_file_ids": ["file-1"],
                                "runtime_file_names": ["underlag.pdf"],
                                "runtime_file_checksums": ["input-checksum"],
                                "runtime_files": [
                                    {
                                        "id": "file-1",
                                        "name": "underlag.pdf",
                                        "checksum": "input-checksum",
                                        "size": 2048,
                                        "mimetype": "application/pdf",
                                        "file_type": "document",
                                        "text_length": 1024,
                                        "has_text": True,
                                        "has_transcription": False,
                                    }
                                ],
                                "question_binding_references_runtime_input": True,
                                "question_binding_expressions": [
                                    "step_1.output.text",
                                    "step_input.text",
                                ],
                                "upstream_step_orders": [1],
                                "upstream_step_labels": ["Collect the source document"],
                            },
                            "configured_input_type": "text",
                            "configured_output_type": "pdf",
                        }
                    ],
                },
                "redaction": {
                    "applied": True,
                    "policy_version": "flow-evidence-redaction.v3",
                    "masked_fields_count": 2,
                    "masked_paths": [
                        "bundle.run.input_payload_json.api_key",
                        "bundle.debug_export.definition_snapshot.steps[0].output_config.headers.Authorization",
                    ],
                    "masked_fields": [
                        {
                            "path": "bundle.run.input_payload_json.api_key",
                            "key": "api_key",
                            "reason": "sensitive_key",
                        }
                    ],
                },
                "bundle": {
                    "run": FLOW_RUN_PUBLIC_EXAMPLE,
                    "definition_snapshot": {"steps": []},
                    "step_results": [FLOW_RUN_STEP_PUBLIC_EXAMPLE],
                    "step_attempts": [],
                    "result_files": [FLOW_RUN_RESULT_FILE_EXAMPLE],
                    "debug_export": FLOW_RUN_DEBUG_EXPORT_EXAMPLE,
                },
            }
        }
    )

    schema_version: str
    generated_at: datetime
    content_hash: str
    manifest: EvidenceExportManifest
    summary: dict[str, Any]
    redaction: dict[str, Any]
    bundle: dict[str, Any] = Field(
        description=(
            "Open evidence object preserved exactly as hashed; use "
            "FlowRunEvidenceResponse for the typed read-model endpoint."
        )
    )
