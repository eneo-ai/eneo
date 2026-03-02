from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional, TypeAlias
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


JsonObject: TypeAlias = dict[str, Any]
ToolCallMetadata: TypeAlias = dict[str, Any]


class FlowRunStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class FlowStepResultStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class FlowStepAttemptStatus(str, Enum):
    STARTED = "started"
    RETRIED = "retried"
    FAILED = "failed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class FlowStep(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID | None = None
    flow_id: UUID | None = None
    tenant_id: UUID | None = None
    assistant_id: UUID
    step_order: int
    user_description: Optional[str] = None
    input_source: str
    input_type: str
    input_contract: JsonObject | None = None
    output_mode: str
    output_type: str
    output_contract: JsonObject | None = None
    input_bindings: JsonObject | None = None
    output_classification_override: Optional[int] = None
    mcp_policy: str
    input_config: JsonObject | None = None
    output_config: JsonObject | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class FlowSparse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID | None = None
    tenant_id: UUID
    space_id: UUID
    name: str
    description: Optional[str] = None
    created_by_user_id: Optional[UUID] = None
    owner_user_id: Optional[UUID] = None
    published_version: Optional[int] = None
    metadata_json: JsonObject | None = None
    data_retention_days: Optional[int] = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


def _default_flow_steps() -> list[FlowStep]:
    return []


class Flow(FlowSparse):
    steps: list[FlowStep] = Field(default_factory=_default_flow_steps)


class FlowVersion(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    flow_id: UUID
    version: int
    tenant_id: UUID
    definition_checksum: str
    definition_json: JsonObject
    created_at: datetime
    updated_at: datetime


class FlowRun(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    flow_id: UUID
    flow_version: int
    user_id: Optional[UUID] = None
    tenant_id: UUID
    status: FlowRunStatus
    cancelled_at: Optional[datetime] = None
    input_payload_json: JsonObject | None = None
    output_payload_json: JsonObject | None = None
    error_message: Optional[str] = None
    job_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime


class FlowStepResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID | None = None
    flow_run_id: UUID
    flow_id: UUID
    tenant_id: UUID
    step_id: Optional[UUID] = None
    step_order: int
    assistant_id: Optional[UUID] = None
    input_payload_json: JsonObject | None = None
    effective_prompt: Optional[str] = None
    output_payload_json: JsonObject | None = None
    model_parameters_json: JsonObject | None = None
    num_tokens_input: Optional[int] = None
    num_tokens_output: Optional[int] = None
    status: FlowStepResultStatus
    error_message: Optional[str] = None
    flow_step_execution_hash: Optional[str] = None
    tool_calls_metadata: list[ToolCallMetadata] | ToolCallMetadata | None = None
    created_at: datetime
    updated_at: datetime


class FlowStepAttempt(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    flow_run_id: UUID
    flow_id: UUID
    tenant_id: UUID
    step_id: Optional[UUID] = None
    step_order: int
    attempt_no: int
    celery_task_id: Optional[str] = None
    status: FlowStepAttemptStatus
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    started_at: datetime
    finished_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
