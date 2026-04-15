from __future__ import annotations

from datetime import datetime
from typing import Literal, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from intric.files.file_models import FilePublic
from intric.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
    JsonObject,
    PlannerPlanEnvelope,
    PlanStatus,
    SessionStatus,
    TargetKind,
)

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


def _default_conversation() -> list[ConversationMessage]:
    return []


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
    flow_id: UUID | None = None
    force_new: bool = False


class SendMessageRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "message": "Build a flow that extracts key dates from uploaded contracts and returns structured JSON.",
                "model_id": "00000000-0000-0000-0000-000000000010",
                "file_ids": ["00000000-0000-0000-0000-000000000099"],
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
    model_id: UUID | None = None
    file_ids: list[UUID] | None = None
    question_answer: JsonObject | None = None
    ui_language: str | None = None


class ApplyPlanRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": {"expected_revision": 12}})

    expected_revision: int | None = None


class RevisePlanRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": {"type": "keep_current_description"}}
    )

    type: Literal["keep_current_description"]


class SessionResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": AI_BUILDER_SESSION_RESPONSE_EXAMPLE}
    )

    session_id: UUID
    status: SessionStatus
    target_kind: TargetKind
    flow_id: UUID | None = None
    latest_plan_id: UUID | None = None
    conversation: list[ConversationMessage] = Field(
        default_factory=_default_conversation
    )
    attachments: list[FilePublic] = Field(
        default_factory=lambda: cast(list[FilePublic], [])
    )
    attachment_warnings: list[str] = Field(default_factory=list)
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
    model_config = ConfigDict(
        json_schema_extra={"example": AI_BUILDER_SESSION_LIST_RESPONSE_EXAMPLE}
    )

    sessions: list[SessionListItemResponse]


class SessionModelOption(BaseModel):
    id: UUID
    name: str
    provider: str


class SessionModelsResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": AI_BUILDER_SESSION_MODELS_RESPONSE_EXAMPLE}
    )

    models: list[SessionModelOption]
    default_model_id: UUID | None = None


class PlanResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": AI_BUILDER_PLAN_RESPONSE_EXAMPLE}
    )

    plan_id: UUID
    session_id: UUID
    status: PlanStatus
    spec_hash: str
    envelope: PlannerPlanEnvelope
    edit_result_json: JsonObject | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SessionPlansResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": AI_BUILDER_SESSION_PLANS_RESPONSE_EXAMPLE}
    )

    plans: list[PlanResponse]


class PlanApprovalResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": AI_BUILDER_PLAN_APPROVAL_RESPONSE_EXAMPLE}
    )

    plan_id: UUID
    status: PlanStatus


class ApplyResultResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": AI_BUILDER_APPLY_RESULT_RESPONSE_EXAMPLE}
    )

    flow_id: UUID
    flow_name: str
    steps_created: int
    steps_updated: int
    steps_removed: int


__all__ = [
    "AI_BUILDER_APPLY_RESULT_RESPONSE_EXAMPLE",
    "AI_BUILDER_PLAN_APPROVAL_RESPONSE_EXAMPLE",
    "AI_BUILDER_PLAN_RESPONSE_EXAMPLE",
    "AI_BUILDER_SESSION_LIST_RESPONSE_EXAMPLE",
    "AI_BUILDER_SESSION_MODELS_RESPONSE_EXAMPLE",
    "AI_BUILDER_SESSION_PLANS_RESPONSE_EXAMPLE",
    "AI_BUILDER_SESSION_RESPONSE_EXAMPLE",
    "ApplyPlanRequest",
    "ApplyResultResponse",
    "CreateSessionRequest",
    "PlanApprovalResponse",
    "PlanResponse",
    "RevisePlanRequest",
    "SendMessageRequest",
    "SessionListItemResponse",
    "SessionListResponse",
    "SessionModelOption",
    "SessionModelsResponse",
    "SessionPlansResponse",
    "SessionResponse",
]
