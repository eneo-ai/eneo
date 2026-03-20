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
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class InputSource(str, enum.Enum):
    FLOW_INPUT = "flow_input"
    PREVIOUS_STEP = "previous_step"
    ALL_PREVIOUS_STEPS = "all_previous_steps"


class InputType(str, enum.Enum):
    TEXT = "text"
    JSON = "json"
    AUDIO = "audio"
    DOCUMENT = "document"
    FILE = "file"
    ANY = "any"


class OutputMode(str, enum.Enum):
    PASS_THROUGH = "pass_through"
    TRANSCRIBE_ONLY = "transcribe_only"
    TEMPLATE_FILL = "template_fill"


class OutputType(str, enum.Enum):
    TEXT = "text"
    JSON = "json"
    PDF = "pdf"
    DOCX = "docx"


class MCPPolicy(str, enum.Enum):
    INHERIT = "inherit"
    RESTRICTED = "restricted"


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


# ---------------------------------------------------------------------------
# FlowDraftSpecCore — the canonical portable flow definition
# ---------------------------------------------------------------------------

JsonObject = dict[str, Any]


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
    type: str  # text | number | date | select | multiselect
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
    """Canonical portable flow definition.

    Used for:
    1. AI planning — the AI outputs this; validated, stored, rendered
    2. Export/import (Phase 2) — portable between Eneo instances
    """

    flow_name: str
    flow_description: str = ""
    steps: list[StepSpec]
    form_fields: list[FormFieldSpec] | None = None

    def spec_hash(self) -> str:
        """Deterministic hash of the spec for integrity verification."""
        serialized = json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# PlannerPlanEnvelope — wraps spec with AI metadata
# ---------------------------------------------------------------------------


class LintWarning(BaseModel):
    step_ref: str | None = None
    code: str
    message: str
    severity: LintSeverity = LintSeverity.WARNING


class PlannerPlanEnvelope(BaseModel):
    """Wraps FlowDraftSpecCore with AI session metadata.

    This separation keeps the portable schema clean.
    Export strips the envelope; AI output includes it.
    """

    spec: FlowDraftSpecCore
    assumptions: list[str] = Field(default_factory=list)
    lint_warnings: list[LintWarning] = Field(default_factory=list)
    risk_acknowledgments: list[str] = Field(default_factory=list)
    plan_rationale: str | None = None
    reasoning: str | None = None  # Chain-of-thought from the LLM (not shown to user)


# ---------------------------------------------------------------------------
# FlowChangeSet — internal execution contract for materializer
# ---------------------------------------------------------------------------


class AssistantToCreate(BaseModel):
    plan_step_ref: str
    assistant_spec: AssistantSpec


class AssistantToUpdate(BaseModel):
    existing_step_id: UUID
    existing_assistant_id: UUID
    assistant_spec: AssistantSpec


class AssistantToDelete(BaseModel):
    step_id: UUID
    assistant_id: UUID


class CompiledStep(BaseModel):
    """A step ready for FlowService, with placeholder or real assistant_id."""

    plan_step_ref: str
    change_kind: StepChangeKind
    step_order: int
    user_description: str | None = None
    assistant_id: UUID | None = None  # None = needs creation, filled by executor
    input_source: str
    input_type: str
    output_mode: str
    output_type: str
    mcp_policy: str
    input_bindings: JsonObject | None = None
    input_contract: JsonObject | None = None
    output_contract: JsonObject | None = None
    input_config: JsonObject | None = None
    output_config: JsonObject | None = None


class FlowChangeSet(BaseModel):
    """Internal execution contract — separates 'what to change' from 'how'.

    Produced by the pure compiler, consumed by the executor.
    """

    flow_name: str
    flow_description: str
    description_override_manual: bool = False
    assistants_to_create: list[AssistantToCreate] = Field(default_factory=list)
    assistants_to_update: list[AssistantToUpdate] = Field(default_factory=list)
    assistants_to_delete: list[AssistantToDelete] = Field(default_factory=list)
    compiled_steps: list[CompiledStep] = Field(default_factory=list)
    metadata_json: JsonObject | None = None


# ---------------------------------------------------------------------------
# BuilderSession + BuilderPlan — domain records
# ---------------------------------------------------------------------------


class ConversationMessage(BaseModel):
    role: str  # "user" | "assistant" | "system" | "tool"
    content: str | None = None
    timestamp: datetime | None = None
    tool_calls: list[JsonObject] | None = None
    tool_call_id: str | None = None  # For role="tool" messages
    metadata: JsonObject | None = None


class BuilderSession(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    space_id: UUID
    flow_id: UUID | None = None  # None for create sessions
    target_kind: TargetKind
    status: SessionStatus = SessionStatus.CHATTING
    actor_user_id: UUID
    conversation: list[ConversationMessage] = Field(default_factory=list)
    latest_plan_id: UUID | None = None
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
    edit_result_json: JsonObject | None = None  # CompiledEditResult for edit-mode plans
    created_at: datetime | None = None
    updated_at: datetime | None = None


# ---------------------------------------------------------------------------
# API request/response models
# ---------------------------------------------------------------------------

AI_BUILDER_SESSION_RESPONSE_EXAMPLE: JsonObject = {
    "session_id": "00000000-0000-0000-0000-000000000701",
    "status": "chatting",
    "target_kind": "create",
    "flow_id": None,
    "latest_plan_id": "00000000-0000-0000-0000-000000000702",
    "conversation": [
        {
            "role": "user",
            "content": "Build a flow that transcribes uploaded audio and returns a PDF summary.",
            "timestamp": "2026-03-17T10:00:00Z",
        },
        {
            "role": "assistant",
            "content": "I need one more detail about the final PDF format.",
            "timestamp": "2026-03-17T10:00:03Z",
        },
    ],
    "created_at": "2026-03-17T10:00:00Z",
    "updated_at": "2026-03-17T10:00:03Z",
}

AI_BUILDER_SESSION_LIST_RESPONSE_EXAMPLE: JsonObject = {
    "sessions": [
        {
            "session_id": "00000000-0000-0000-0000-000000000701",
            "space_id": "00000000-0000-0000-0000-000000000020",
            "status": "awaiting_approval",
            "target_kind": "create",
            "flow_id": None,
            "latest_plan_id": "00000000-0000-0000-0000-000000000702",
            "draft_title": "Employee Review Summary",
            "created_at": "2026-03-17T10:00:00Z",
            "updated_at": "2026-03-17T10:02:00Z",
        }
    ]
}

AI_BUILDER_SESSION_MODELS_RESPONSE_EXAMPLE: JsonObject = {
    "models": [
        {
            "id": "00000000-0000-0000-0000-000000000710",
            "name": "gpt-5.4",
            "provider": "openai",
        }
    ],
    "default_model_id": "00000000-0000-0000-0000-000000000710",
}

AI_BUILDER_PLAN_RESPONSE_EXAMPLE: JsonObject = {
    "plan_id": "00000000-0000-0000-0000-000000000702",
    "session_id": "00000000-0000-0000-0000-000000000701",
    "status": "proposed",
    "spec_hash": "abc123def456",
    "envelope": {
        "spec": {
            "flow_name": "Employee Review Summary",
            "flow_description": "Transcribe a review conversation and generate a PDF summary.",
            "steps": [
                {
                    "plan_step_ref": "step_a",
                    "name": "Transcribe uploaded audio",
                    "assistant_spec": {
                        "instructions": "Transcribe the uploaded audio into Swedish text.",
                        "model_ref": "model:gpt-5.4",
                        "knowledge_refs": [],
                    },
                    "mcp_policy": "inherit",
                    "input_source": "flow_input",
                    "input_type": "audio",
                    "output_mode": "transcribe_only",
                    "output_type": "text",
                    "input_bindings": None,
                    "input_contract": None,
                    "output_contract": None,
                    "input_config": None,
                    "output_config": None,
                },
                {
                    "plan_step_ref": "step_b",
                    "name": "Create PDF summary",
                    "assistant_spec": {
                        "instructions": "Summarize the transcription into a professional PDF.",
                        "model_ref": "model:gpt-5.4",
                        "knowledge_refs": [],
                    },
                    "mcp_policy": "inherit",
                    "input_source": "previous_step",
                    "input_type": "text",
                    "output_mode": "pass_through",
                    "output_type": "pdf",
                    "input_bindings": {"question": "{{ step_a.output.text }}"},
                    "input_contract": None,
                    "output_contract": None,
                    "input_config": None,
                    "output_config": None,
                },
            ],
            "form_fields": [
                {
                    "name": "employee_name",
                    "type": "text",
                    "label": "Employee name",
                    "required": True,
                    "options": None,
                }
            ],
        },
        "assumptions": ["Uploaded audio is clear enough to transcribe."],
        "lint_warnings": [],
        "risk_acknowledgments": [],
        "plan_rationale": "A two-step flow keeps the transcription and summary concerns separate.",
    },
    "created_at": "2026-03-17T10:02:00Z",
    "updated_at": "2026-03-17T10:02:00Z",
}

AI_BUILDER_SESSION_PLANS_RESPONSE_EXAMPLE: JsonObject = {
    "plans": [AI_BUILDER_PLAN_RESPONSE_EXAMPLE],
}

AI_BUILDER_PLAN_APPROVAL_RESPONSE_EXAMPLE: JsonObject = {
    "plan_id": "00000000-0000-0000-0000-000000000702",
    "status": "approved",
}

AI_BUILDER_APPLY_RESULT_RESPONSE_EXAMPLE: JsonObject = {
    "flow_id": "00000000-0000-0000-0000-000000000001",
    "flow_name": "Employee Review Summary",
    "steps_created": 2,
    "steps_updated": 0,
    "steps_removed": 0,
}


class CreateSessionRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "target_kind": "create",
                "space_id": "00000000-0000-0000-0000-000000000001",
                "force_new": False,
            }
        }
    )

    target_kind: TargetKind
    space_id: UUID
    flow_id: UUID | None = None  # Required for edit
    force_new: bool = False


class SendMessageRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "message": "Build a flow that extracts key dates from uploaded contracts and returns structured JSON.",
                "model_id": "00000000-0000-0000-0000-000000000010",
                "question_answer": {
                    "question_id": "final_output_mode",
                    "selected_option_ids": ["structured_json"],
                    "selected_values": ["structured_json"],
                },
                "ui_language": "en",
            }
        }
    )

    message: str = Field(max_length=50_000)
    model_id: UUID | None = None  # Override the default planner model
    question_answer: JsonObject | None = None
    ui_language: str | None = None


class ApplyPlanRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "expected_revision": 12,
            }
        }
    )

    expected_revision: int | None = None  # Required for edit sessions


class RevisePlanRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "type": "keep_current_description",
            }
        }
    )

    type: Literal["keep_current_description", "regenerate_description"]


class SessionResponse(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": AI_BUILDER_SESSION_RESPONSE_EXAMPLE})

    session_id: UUID
    status: SessionStatus
    target_kind: TargetKind
    flow_id: UUID | None = None
    latest_plan_id: UUID | None = None
    conversation: list[ConversationMessage] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SessionListItemResponse(BaseModel):
    session_id: UUID
    space_id: UUID
    status: SessionStatus
    target_kind: TargetKind
    flow_id: UUID | None = None
    latest_plan_id: UUID | None = None
    draft_title: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SessionListResponse(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": AI_BUILDER_SESSION_LIST_RESPONSE_EXAMPLE})

    sessions: list[SessionListItemResponse]


class SessionModelOption(BaseModel):
    id: UUID
    name: str
    provider: str


class SessionModelsResponse(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": AI_BUILDER_SESSION_MODELS_RESPONSE_EXAMPLE})

    models: list[SessionModelOption]
    default_model_id: UUID | None = None


class PlanResponse(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": AI_BUILDER_PLAN_RESPONSE_EXAMPLE})

    plan_id: UUID
    session_id: UUID
    status: PlanStatus
    spec_hash: str
    envelope: PlannerPlanEnvelope
    edit_result_json: JsonObject | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SessionPlansResponse(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": AI_BUILDER_SESSION_PLANS_RESPONSE_EXAMPLE})

    plans: list[PlanResponse]


class PlanApprovalResponse(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": AI_BUILDER_PLAN_APPROVAL_RESPONSE_EXAMPLE})

    plan_id: UUID
    status: PlanStatus


class ApplyResultResponse(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": AI_BUILDER_APPLY_RESULT_RESPONSE_EXAMPLE})

    flow_id: UUID
    flow_name: str
    steps_created: int
    steps_updated: int
    steps_removed: int


# ---------------------------------------------------------------------------
# SSE event payload models
# ---------------------------------------------------------------------------


class StructuredQuestionOptionPayload(BaseModel):
    id: str | None = None
    label: str
    value: Any | None = None
    description: str | None = None


class StructuredQuestionPayload(BaseModel):
    question_id: str
    question: str
    options: list[StructuredQuestionOptionPayload]
    selection_mode: Literal["single", "multi"]
    allow_custom: bool


class AIBuilderTextEventData(BaseModel):
    text: str


class AIBuilderStatusEventData(BaseModel):
    status: str


class AIBuilderErrorEventData(BaseModel):
    error: str
    message: str
    code: str
    phase: str
    intric_error_code: int | None = None
    request_id: str | None = None


class KeyDecisionPayload(BaseModel):
    topic: str
    decision: str


class RequirementsSummaryPayload(BaseModel):
    requirements_version: str | None = None
    summary: str
    key_decisions: list[KeyDecisionPayload]
    input_description: str
    output_description: str
    assumptions: list[str] = Field(default_factory=list)
    manual_setup_notes: list[str] = Field(default_factory=list)


class AIBuilderPlanEventData(BaseModel):
    plan_id: UUID
    envelope: PlannerPlanEnvelope
    edit_diff: JsonObject | None = None  # FlowEditDiff for edit-mode plans
    edit_confidence: str | None = None  # EditConfidence for edit-mode plans
    edit_warnings: list[str] | None = None
    edit_advisories: list[JsonObject] | None = None
    edit_risk_flags: list[str] | None = None
