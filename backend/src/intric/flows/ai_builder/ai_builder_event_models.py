from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from intric.flows.ai_builder.ai_builder_domain_models import (
    JsonObject,
    PlannerPlanEnvelope,
)


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
    requires_confirm: bool = False


class AIBuilderTextEventData(BaseModel):
    text: str


class AIBuilderStatusEventData(BaseModel):
    status: str


class AIBuilderErrorEventData(BaseModel):
    error: str = ""
    message: str
    code: str
    phase: str = "router"
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
    edit_diff: JsonObject | None = None
    edit_confidence: str | None = None
    edit_warnings: list[str] | None = None
    edit_advisories: list[JsonObject] | None = None
    edit_risk_flags: list[str] | None = None


__all__ = [
    "AIBuilderErrorEventData",
    "AIBuilderPlanEventData",
    "AIBuilderStatusEventData",
    "AIBuilderTextEventData",
    "KeyDecisionPayload",
    "RequirementsSummaryPayload",
    "StructuredQuestionOptionPayload",
    "StructuredQuestionPayload",
]
