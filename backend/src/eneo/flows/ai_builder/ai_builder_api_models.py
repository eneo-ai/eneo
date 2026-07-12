from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Literal, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from eneo.files.file_models import FilePublic
from eneo.flows.ai_builder.ai_builder_attachment_context import (
    AI_BUILDER_MAX_ATTACHMENTS,
)
from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
    AIBuilderQuestionAnswerRequest,
    RequirementsConfirmationMetadata,
    SlotClassificationMetadata,
    StructuredQuestionAnswerMetadata,
)
from eneo.flows.ai_builder.ai_builder_domain_models import (
    BuilderTurnState,
    FlowBuilderProposalContent,
    PlanStatus,
    SessionStatus,
    TargetKind,
)
from eneo.flows.ai_builder.ai_builder_error_contract import AIBuilderPublicError
from eneo.flows.ai_builder.ai_builder_event_models import (
    RequirementsSummaryPayload,
    StructuredQuestionPayload,
)
from eneo.flows.ai_builder.ai_builder_plan_edit_context import (
    AIBuilderPlanEditContext,
)
from eneo.flows.ai_builder.ai_builder_telemetry_models import (
    SessionTelemetrySummary,
)
from eneo.flows.domain.flow import FlowPersistedJsonObject

AI_BUILDER_SESSION_RESPONSE_EXAMPLE: FlowPersistedJsonObject = {
    "session_id": "00000000-0000-0000-0000-000000000701",
    "status": "chatting",
    "target_kind": "create",
    "flow_id": None,
    "latest_plan_id": "00000000-0000-0000-0000-000000000702",
    "latest_turn": {
        "client_turn_id": "00000000-0000-0000-0000-000000000703",
        "state": "committed",
        "user_message_id": "019db164-9eab-7843-baa1-229e595cde04",
        "error": None,
        "requires_duplicate_provider_spend_acknowledgement": False,
        "retry_request": {
            "client_turn_id": "00000000-0000-0000-0000-000000000703",
            "message": "Build a flow that transcribes uploaded audio and returns a PDF summary.",
            "ui_language": "en",
        },
    },
    "telemetry": {
        "planner_request_count": 2,
        "clarification_question_count": 1,
        "prompt_tokens_total": 1200,
        "completion_tokens_total": 240,
        "total_tokens_total": 1440,
        "tool_call_count_total": 1,
        "auxiliary_llm_call_count": 0,
        "architecture_commit_count": 1,
        "repair_attempts_total": 0,
        "parse_repair_attempts_total": 0,
        "wall_clock_ms_total": 3200,
        "llm_calls_made_total": 2,
        "token_usage_estimated": False,
        "last_request_id": "req-123",
        "last_model": "openai/gpt-5.4",
        "last_finish_reason": "stop",
        "last_outcome_kind": "dispatched",
        "last_token_usage_source": "provider",
        "last_token_usage_estimated": False,
    },
    "conversation": [
        {
            "message_id": "019db164-9eab-7843-baa1-229e595cde04",
            "role": "user",
            "content": "Build a flow that transcribes uploaded audio and returns a PDF summary.",
            "timestamp": "2026-03-17T10:00:00Z",
        },
        {
            "message_id": "019db164-9ec0-7f11-8b2e-2a1cd92f6a3f",
            "role": "assistant",
            "content": "I need one more detail about the final PDF format.",
            "timestamp": "2026-03-17T10:00:03Z",
        },
    ],
    "created_at": "2026-03-17T10:00:00Z",
    "updated_at": "2026-03-17T10:00:03Z",
}

AI_BUILDER_SESSION_LIST_RESPONSE_EXAMPLE: FlowPersistedJsonObject = {
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

AI_BUILDER_SESSION_MODELS_RESPONSE_EXAMPLE: FlowPersistedJsonObject = {
    "models": [
        {
            "id": "00000000-0000-0000-0000-000000000710",
            "name": "gpt-5.4",
            "provider": "openai",
        }
    ],
    "default_model_id": "00000000-0000-0000-0000-000000000710",
}

AI_BUILDER_PLAN_RESPONSE_EXAMPLE: FlowPersistedJsonObject = {
    "plan_id": "00000000-0000-0000-0000-000000000702",
    "session_id": "00000000-0000-0000-0000-000000000701",
    "status": "proposed",
    "spec_hash": "abc123def456",
    "proposal": {
        "spec": {
            "flow_name": "Employee Review Summary",
            "flow_description": "Transcribe a review conversation and generate a PDF summary.",
            "steps": [
                {
                    "plan_step_ref": "step_a",
                    "name": "Transcribe uploaded audio",
                    "assistant_spec": {
                        "instructions": "Transcribe the uploaded audio into Swedish text.",
                        "model_ref": None,
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
                        "model_ref": "model.gpt-5-4",
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

AI_BUILDER_SESSION_PLANS_RESPONSE_EXAMPLE: FlowPersistedJsonObject = {
    "plans": [AI_BUILDER_PLAN_RESPONSE_EXAMPLE],
}

AI_BUILDER_PLAN_APPROVAL_RESPONSE_EXAMPLE: FlowPersistedJsonObject = {
    "plan_id": "00000000-0000-0000-0000-000000000702",
    "status": "approved",
}

AI_BUILDER_APPLY_RESULT_RESPONSE_EXAMPLE: FlowPersistedJsonObject = {
    "flow_id": "00000000-0000-0000-0000-000000000001",
    "flow_name": "Employee Review Summary",
    "steps_created": 2,
    "steps_updated": 0,
    "steps_removed": 0,
}


def _default_conversation() -> list["AIBuilderConversationMessage"]:
    return []


class AIBuilderConversationMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_id: str
    role: Literal["user", "assistant"]
    content: str | None = None
    timestamp: datetime | None = None
    question: StructuredQuestionPayload | None = None
    requirements_summary: RequirementsSummaryPayload | None = None
    question_answer: StructuredQuestionAnswerMetadata | None = None
    requirements_confirmation: RequirementsConfirmationMetadata | None = None


class AIBuilderClassifierDiagnostic(SlotClassificationMetadata):
    message_id: str


class AIBuilderClassifierDiagnosticsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: UUID
    classifier_runs: list[AIBuilderClassifierDiagnostic]


class CreateSessionRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "target_kind": "create",
                "space_id": "00000000-0000-0000-0000-000000000001",
                "force_new": False,
            }
        },
    )

    target_kind: TargetKind
    space_id: UUID
    flow_id: UUID | None = None
    force_new: bool = False


class SendMessageRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "client_turn_id": "00000000-0000-0000-0000-000000000703",
                "message": "Build a flow that extracts key dates from uploaded contracts and returns structured JSON.",
                "model_id": "00000000-0000-0000-0000-000000000010",
                "file_ids": ["00000000-0000-0000-0000-000000000099"],
                "question_answer": {
                    "kind": "structured_question_answer",
                    "question_id": "terminal_output",
                    "selected_option_ids": ["structured_json"],
                    "selected_values": ["structured_json"],
                },
                "edit_context": {
                    "scope": "step",
                    "plan_id": "00000000-0000-0000-0000-000000000702",
                    "target_plan_step_ref": "step_b",
                    "target_step_name": "Create PDF summary",
                    "target_step_number": 2,
                },
                "ui_language": "en",
                "acknowledge_duplicate_provider_spend": False,
            }
        },
    )

    client_turn_id: UUID = Field(
        description=(
            "Caller-generated identity for the latest logical session turn. Reuse it "
            "only when retrying the same request payload."
        )
    )
    message: str = Field(max_length=50_000)
    model_id: UUID | None = None
    file_ids: list[UUID] | None = Field(
        default=None,
        max_length=AI_BUILDER_MAX_ATTACHMENTS,
    )
    question_answer: AIBuilderQuestionAnswerRequest | None = None
    edit_context: AIBuilderPlanEditContext | None = None
    ui_language: str | None = Field(default=None, max_length=16)
    acknowledge_duplicate_provider_spend: bool = Field(
        default=False,
        description=(
            "Explicitly acknowledges that retrying a provider-outcome-unknown turn "
            "can repeat provider work and cost."
        ),
    )

    def request_fingerprint(self) -> str:
        """Hash the stable caller-authored logical request, not mutable provider config."""
        normalized = self.model_dump(
            mode="json",
            exclude={
                "client_turn_id",
                "acknowledge_duplicate_provider_spend",
            },
        )
        normalized["request_fingerprint_algorithm_version"] = 1
        normalized["file_ids"] = sorted(
            str(file_id) for file_id in (self.file_ids or [])
        )
        payload = json.dumps(
            normalized,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def retry_snapshot(self) -> FlowPersistedJsonObject:
        """Return the exact bounded request retained for latest-turn recovery."""
        return self.model_dump(
            mode="json",
            exclude={"acknowledge_duplicate_provider_spend"},
            exclude_none=True,
        )


class ApplyPlanRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"example": {"expected_revision": 12}},
    )

    expected_revision: int | None = None


class RevisePlanRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"example": {"type": "keep_current_description"}},
    )

    type: Literal["keep_current_description"]


class AIBuilderTurnLifecycleResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_turn_id: UUID
    state: BuilderTurnState
    user_message_id: UUID
    error: AIBuilderPublicError | None = None
    requires_duplicate_provider_spend_acknowledgement: bool
    retry_request: SendMessageRequest


class SessionResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": AI_BUILDER_SESSION_RESPONSE_EXAMPLE}
    )

    session_id: UUID
    status: SessionStatus
    target_kind: TargetKind
    flow_id: UUID | None = None
    latest_plan_id: UUID | None = None
    latest_turn: AIBuilderTurnLifecycleResponse | None = None
    telemetry: "SessionTelemetrySummary | None" = None
    conversation: list[AIBuilderConversationMessage] = Field(
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
    proposal: FlowBuilderProposalContent
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
    "AIBuilderConversationMessage",
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
    "SessionTelemetrySummary",
]
