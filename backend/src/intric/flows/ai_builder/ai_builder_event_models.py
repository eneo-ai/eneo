from __future__ import annotations

from typing import Literal, TypeAlias
from uuid import UUID

from pydantic import BaseModel, Field

from intric.flows.ai_builder.ai_builder_domain_models import (
    PlannerPlanEnvelope,
)
from intric.flows.ai_builder.ai_builder_edit_models import BuilderPlanEditResult

JsonScalar: TypeAlias = str | int | float | bool | None


class StructuredQuestionOptionPayload(BaseModel):
    id: str | None = None
    label: str
    value: JsonScalar = None
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
    edit_result_json: BuilderPlanEditResult | None = None


AI_BUILDER_SSE_MODELS: tuple[type[BaseModel], ...] = (
    AIBuilderTextEventData,
    AIBuilderStatusEventData,
    StructuredQuestionOptionPayload,
    StructuredQuestionPayload,
    KeyDecisionPayload,
    RequirementsSummaryPayload,
    AIBuilderPlanEventData,
)


__all__ = [
    "AI_BUILDER_SSE_MODELS",
    "AIBuilderPlanEventData",
    "AIBuilderStatusEventData",
    "AIBuilderTextEventData",
    "KeyDecisionPayload",
    "RequirementsSummaryPayload",
    "StructuredQuestionOptionPayload",
    "StructuredQuestionPayload",
]
