"""Domain models for the AI Flow Builder.

Defines the canonical schemas:
- FlowDraftSpecCore: portable flow definition (planning + export/import)
- PlannerPlanEnvelope: wraps spec with AI session metadata
- FlowChangeSet: internal execution contract for the materializer
- BuilderSession / BuilderPlan: session and plan domain records
"""

from __future__ import annotations

import enum
import hashlib
import json
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from intric.flows.enums import (
    AIBuilderInputSource as InputSource,
    AIBuilderInputType as InputType,
    FlowInputSource,
    FlowInputType,
    AIBuilderOutputMode as OutputMode,
    FlowMcpPolicy as MCPPolicy,
    FlowOutputMode,
    FlowOutputType as OutputType,
)


class SessionStatus(str, enum.Enum):
    CHATTING = "chatting"
    AWAITING_APPROVAL = "awaiting_approval"
    APPLYING = "applying"
    APPLIED = "applied"
    CANCELLED = "cancelled"


class PlanStatus(str, enum.Enum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    APPLIED = "applied"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class TargetKind(str, enum.Enum):
    CREATE = "create"
    EDIT = "edit"


class StepChangeKind(str, enum.Enum):
    ADDED = "added"
    MODIFIED = "modified"
    REMOVED = "removed"
    UNCHANGED = "unchanged"


class LintSeverity(str, enum.Enum):
    WARNING = "warning"
    INFO = "info"


JsonObject = dict[str, Any]


def _default_lint_warnings() -> list[LintWarning]:
    return []


def _default_assistants_to_create() -> list[AssistantToCreate]:
    return []


def _default_assistants_to_update() -> list[AssistantToUpdate]:
    return []


def _default_assistants_to_delete() -> list[AssistantToDelete]:
    return []


def _default_compiled_steps() -> list[CompiledStep]:
    return []


def _default_conversation() -> list[ConversationMessage]:
    return []


class AssistantSpec(BaseModel):
    """Inline assistant definition embedded in each step spec."""

    instructions: str
    model_ref: str | None = None
    knowledge_refs: list[str] = Field(default_factory=list)

    @field_validator("model_ref")
    @classmethod
    def normalize_model_ref(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("knowledge_refs")
    @classmethod
    def normalize_knowledge_refs(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for raw in values:
            candidate = str(raw).strip()
            if not candidate or candidate in seen:
                continue
            normalized.append(candidate)
            seen.add(candidate)
        return normalized


class StepSpec(BaseModel):
    """Single step in a FlowDraftSpecCore."""

    plan_step_ref: str = Field(
        description="Stable reference like 'step_a', 'step_b'. Used for variable bindings."
    )
    existing_step_ref: str | None = Field(
        default=None,
        description="Server-provided alias for an existing step (not raw UUID). Set when modifying.",
    )
    name: str = Field(description="User-visible step name (user_description).")
    assistant_spec: AssistantSpec
    mcp_policy: MCPPolicy = MCPPolicy.INHERIT
    input_source: InputSource
    input_type: InputType = InputType.TEXT
    output_mode: OutputMode = OutputMode.PASS_THROUGH
    output_type: OutputType = OutputType.TEXT
    input_bindings: JsonObject | None = None
    input_contract: JsonObject | None = None
    output_contract: JsonObject | None = None
    input_config: JsonObject | None = None
    output_config: JsonObject | None = None

    @field_validator("input_bindings")
    @classmethod
    def normalize_input_bindings(cls, value: JsonObject | None) -> JsonObject | None:
        if value is None:
            return None
        question = value.get("question")
        if isinstance(question, str):
            return {
                **value,
                "question": question.strip(),
            }
        return value


_VALID_FORM_FIELD_TYPES = {"text", "number", "date", "select", "multiselect"}

_FORM_FIELD_TYPE_COERCIONS: dict[str, str] = {
    "textarea": "text",
    "string": "text",
    "email": "text",
    "url": "text",
    "phone": "text",
    "tel": "text",
    "password": "text",
    "integer": "number",
    "float": "number",
    "decimal": "number",
    "dropdown": "select",
    "radio": "select",
    "enum": "select",
    "checkbox": "multiselect",
    "checkboxes": "multiselect",
    "multi_select": "multiselect",
    "multi-select": "multiselect",
    "tags": "multiselect",
    "datetime": "date",
    "time": "date",
}


class FormFieldSpec(BaseModel):
    """Form field definition for flow runtime input forms."""

    name: str
    type: str
    label: str
    required: bool = False
    options: list[str] | None = None

    @field_validator("type")
    @classmethod
    def coerce_field_type(cls, v: str) -> str:
        normalized = v.strip().casefold()
        if normalized in _VALID_FORM_FIELD_TYPES:
            return normalized
        coerced = _FORM_FIELD_TYPE_COERCIONS.get(normalized)
        if coerced is not None:
            return coerced
        return "text"


class FlowDraftSpecCore(BaseModel):
    """Canonical portable flow definition."""

    flow_name: str
    flow_description: str = ""
    steps: list[StepSpec]
    form_fields: list[FormFieldSpec] | None = None

    def spec_hash(self) -> str:
        serialized = json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class LintWarning(BaseModel):
    step_ref: str | None = None
    code: str
    message: str
    severity: LintSeverity = LintSeverity.WARNING


class PlannerPlanEnvelope(BaseModel):
    """Wraps FlowDraftSpecCore with AI session metadata."""

    spec: FlowDraftSpecCore
    assumptions: list[str] = Field(default_factory=list)
    lint_warnings: list[LintWarning] = Field(default_factory=_default_lint_warnings)
    risk_acknowledgments: list[str] = Field(default_factory=list)
    reasoning: str | None = None
    plan_rationale: str | None = None


class AssistantToCreate(BaseModel):
    plan_step_ref: str
    assistant_spec: AssistantSpec


class AssistantToUpdate(BaseModel):
    existing_step_ref: str | None = None
    existing_step_id: UUID | None = None
    existing_assistant_id: UUID | None = None
    assistant_spec: AssistantSpec


class AssistantToDelete(BaseModel):
    existing_step_ref: str | None = None
    step_id: UUID | None = None
    assistant_id: UUID | None = None


class CompiledStep(BaseModel):
    plan_step_ref: str
    change_kind: StepChangeKind
    step_order: int
    user_description: str
    input_source: FlowInputSource
    input_type: FlowInputType
    output_mode: FlowOutputMode
    output_type: OutputType
    mcp_policy: MCPPolicy
    assistant_id: UUID | None = None
    existing_step_ref: str | None = None
    input_bindings: JsonObject | None = None
    input_contract: JsonObject | None = None
    output_contract: JsonObject | None = None
    input_config: JsonObject | None = None
    output_config: JsonObject | None = None


class FlowChangeSet(BaseModel):
    flow_name: str
    flow_description: str
    description_override_manual: bool = False
    assistants_to_create: list[AssistantToCreate] = Field(
        default_factory=_default_assistants_to_create
    )
    assistants_to_update: list[AssistantToUpdate] = Field(
        default_factory=_default_assistants_to_update
    )
    assistants_to_delete: list[AssistantToDelete] = Field(
        default_factory=_default_assistants_to_delete
    )
    compiled_steps: list[CompiledStep] = Field(default_factory=_default_compiled_steps)
    metadata_json: JsonObject | None = None


class ConversationMessage(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    role: str
    content: str | None = None
    tool_call_id: str | None = Field(
        default=None,
        description="Planner-internal correlation id for a tool response turn.",
    )
    tool_calls: list[JsonObject] | None = Field(
        default=None,
        description=(
            "Planner-internal tool trace metadata kept in the conversation history for debugging "
            "and replay. API consumers should not treat the exact tool trace shape as a stable "
            "business contract."
        ),
    )
    metadata: JsonObject | None = None
    timestamp: datetime | None = None


class BuilderSession(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    space_id: UUID
    actor_user_id: UUID | None = None
    target_kind: TargetKind
    flow_id: UUID | None = None
    latest_plan_id: UUID | None = None
    status: SessionStatus = SessionStatus.CHATTING
    conversation: list[ConversationMessage] = Field(default_factory=_default_conversation)
    requirements_version: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class BuilderPlan(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    session_id: UUID
    tenant_id: UUID
    status: PlanStatus = PlanStatus.PROPOSED
    spec: FlowDraftSpecCore
    spec_hash: str
    envelope: PlannerPlanEnvelope
    edit_result_json: JsonObject | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


__all__ = [
    "AssistantSpec",
    "AssistantToCreate",
    "AssistantToDelete",
    "AssistantToUpdate",
    "BuilderPlan",
    "BuilderSession",
    "CompiledStep",
    "ConversationMessage",
    "FlowChangeSet",
    "FlowDraftSpecCore",
    "FormFieldSpec",
    "InputSource",
    "InputType",
    "JsonObject",
    "LintSeverity",
    "LintWarning",
    "MCPPolicy",
    "OutputMode",
    "OutputType",
    "PlanStatus",
    "PlannerPlanEnvelope",
    "SessionStatus",
    "StepChangeKind",
    "StepSpec",
    "TargetKind",
]
