from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Final, Literal, TypeAlias, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator

from eneo.flows.ai_builder.ai_builder_domain_models import FlowBuilderProposalContent
from eneo.flows.ai_builder.ai_builder_error_contract import AIBuilderErrorEvent
from eneo.flows.ai_builder.ai_builder_telemetry_models import (
    SessionTelemetrySummary,
)

JsonScalar: TypeAlias = str | int | float | bool | None


class AIBuilderStatus(StrEnum):
    ARCHITECTURE_COMMITTED = "architecture_committed"
    ARCHITECTURE_REVISED = "architecture_revised"
    REPAIRING = "repairing"


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
    input_field_collection: bool = Field(
        default=False,
        exclude_if=lambda value: value is False,
    )


class AIBuilderTextEventData(BaseModel):
    text: str


class AIBuilderStatusEventData(BaseModel):
    status: AIBuilderStatus


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

    @field_validator("key_decisions", mode="after")
    @classmethod
    def _one_decision_per_topic(
        cls, decisions: list[KeyDecisionPayload]
    ) -> list[KeyDecisionPayload]:
        # A topic names a single decision; the planner occasionally repeats a
        # topic, which would render as duplicate rows. Keep the first occurrence
        # so the summary stays unique and the UI's per-topic keys do not collide.
        seen: set[str] = set()
        unique: list[KeyDecisionPayload] = []
        for decision in decisions:
            if decision.topic in seen:
                continue
            seen.add(decision.topic)
            unique.append(decision)
        return unique


class AIBuilderPlanEventData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: UUID
    proposal: FlowBuilderProposalContent


class AIBuilderTextEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event: Literal["text"] = "text"
    data: AIBuilderTextEventData


class AIBuilderStatusEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event: Literal["status"] = "status"
    data: AIBuilderStatusEventData


class AIBuilderQuestionEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event: Literal["question"] = "question"
    data: StructuredQuestionPayload


class AIBuilderRequirementsSummaryEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event: Literal["requirements_summary"] = "requirements_summary"
    data: RequirementsSummaryPayload


class AIBuilderPlanEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event: Literal["plan"] = "plan"
    data: AIBuilderPlanEventData


class AIBuilderUsageEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event: Literal["usage"] = "usage"
    data: SessionTelemetrySummary


class AIBuilderDoneEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event: Literal["done"] = "done"
    data: Literal[""] = ""


AIBuilderStreamEvent: TypeAlias = Annotated[
    AIBuilderTextEvent
    | AIBuilderStatusEvent
    | AIBuilderQuestionEvent
    | AIBuilderRequirementsSummaryEvent
    | AIBuilderPlanEvent
    | AIBuilderUsageEvent
    | AIBuilderErrorEvent
    | AIBuilderDoneEvent,
    Field(discriminator="event"),
]

_AI_BUILDER_STREAM_EVENT_ADAPTER: Final[TypeAdapter[AIBuilderStreamEvent]] = (
    TypeAdapter(AIBuilderStreamEvent)
)


def _event_name(model: type[BaseModel]) -> str:
    value = model.model_fields["event"].default
    if not isinstance(value, str):
        raise TypeError(f"{model.__name__}.event must have a string default")
    return value


SSE_EVENT_TEXT: Final = _event_name(AIBuilderTextEvent)
SSE_EVENT_PLAN: Final = _event_name(AIBuilderPlanEvent)
SSE_EVENT_QUESTION: Final = _event_name(AIBuilderQuestionEvent)
SSE_EVENT_REQUIREMENTS_SUMMARY: Final = _event_name(AIBuilderRequirementsSummaryEvent)
SSE_EVENT_ERROR: Final = _event_name(AIBuilderErrorEvent)
SSE_EVENT_STATUS: Final = _event_name(AIBuilderStatusEvent)
SSE_EVENT_USAGE: Final = _event_name(AIBuilderUsageEvent)
SSE_EVENT_DONE: Final = _event_name(AIBuilderDoneEvent)

AI_BUILDER_STREAM_EVENT_MODELS: tuple[type[BaseModel], ...] = (
    AIBuilderTextEvent,
    AIBuilderStatusEvent,
    AIBuilderQuestionEvent,
    AIBuilderRequirementsSummaryEvent,
    AIBuilderPlanEvent,
    AIBuilderUsageEvent,
    AIBuilderErrorEvent,
    AIBuilderDoneEvent,
)

AI_BUILDER_SCHEMA_HOIST_MODELS: tuple[type[BaseModel], ...] = (
    AIBuilderTextEventData,
    AIBuilderStatusEventData,
    StructuredQuestionOptionPayload,
    StructuredQuestionPayload,
    KeyDecisionPayload,
    RequirementsSummaryPayload,
    AIBuilderPlanEventData,
    SessionTelemetrySummary,
    *AI_BUILDER_STREAM_EVENT_MODELS,
)


def ai_builder_stream_event_schema() -> dict[str, object]:
    schema = _AI_BUILDER_STREAM_EVENT_ADAPTER.json_schema(
        ref_template="#/components/schemas/{model}"
    )
    schema.pop("$defs", None)
    return cast(dict[str, object], schema)


__all__ = [
    "AI_BUILDER_SCHEMA_HOIST_MODELS",
    "AI_BUILDER_STREAM_EVENT_MODELS",
    "AIBuilderDoneEvent",
    "AIBuilderErrorEvent",
    "AIBuilderPlanEventData",
    "AIBuilderPlanEvent",
    "AIBuilderQuestionEvent",
    "AIBuilderRequirementsSummaryEvent",
    "AIBuilderStatus",
    "AIBuilderStatusEventData",
    "AIBuilderStatusEvent",
    "AIBuilderStreamEvent",
    "AIBuilderTextEventData",
    "AIBuilderTextEvent",
    "AIBuilderUsageEvent",
    "KeyDecisionPayload",
    "RequirementsSummaryPayload",
    "SSE_EVENT_DONE",
    "SSE_EVENT_ERROR",
    "SSE_EVENT_PLAN",
    "SSE_EVENT_QUESTION",
    "SSE_EVENT_REQUIREMENTS_SUMMARY",
    "SSE_EVENT_STATUS",
    "SSE_EVENT_TEXT",
    "SSE_EVENT_USAGE",
    "StructuredQuestionOptionPayload",
    "StructuredQuestionPayload",
    "ai_builder_stream_event_schema",
]
