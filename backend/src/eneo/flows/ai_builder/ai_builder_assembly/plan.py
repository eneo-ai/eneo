from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from eneo.flows.ai_builder.ai_builder_new_step_compiler import SourceCaptureField
from eneo.flows.ai_builder.ai_builder_new_step_models import (
    DocumentDeliveryMode,
    PreviousFieldRef,
    PreviousOutputRef,
    StructuredFieldDraft,
)
from eneo.flows.flow_authoring_spec import (
    FormFieldSpec,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
)
from eneo.flows.flow_review_policy import FlowStepReviewMode
from eneo.json_types import JsonObject

PlannedStepRole = Literal[
    "reader",
    "transform",
    "body_writer",
    "renderer",
    "transcription",
    "template_fill",
]
UnderlagChannel = Literal[
    "flow_input", "implicit_previous", "field_refs", "text_anchor", "fan_in"
]


@dataclass(frozen=True, slots=True)
class PlannedStep:
    role: PlannedStepRole
    name: str
    instructions: str
    input_source: InputSource
    input_type: InputType
    output_type: OutputType
    output_mode: OutputMode
    underlag_channel: UnderlagChannel
    document_delivery_mode: DocumentDeliveryMode = "not_applicable"
    runtime_required: bool = False
    runtime_max_files: int | None = None
    form_field_refs: tuple[str, ...] = ()
    previous_field_refs: tuple[PreviousFieldRef, ...] = ()
    previous_output_refs: tuple[PreviousOutputRef, ...] = ()
    output_fields: tuple[StructuredFieldDraft, ...] = ()
    model_ref: str | None = None
    knowledge_refs: tuple[str, ...] = ()
    mcp_server_refs: tuple[str, ...] = ()
    mcp_tool_refs: tuple[str, ...] = ()
    citations_requested: bool = False
    review_mode: FlowStepReviewMode | None = None


@dataclass(frozen=True, slots=True)
class FlowAssemblyPlan:
    flow_name: str
    flow_description: str
    form_fields: tuple[FormFieldSpec, ...]
    steps: tuple[PlannedStep, ...]
    terminal_output_schema: JsonObject | None
    source_reader_required_fields: tuple[SourceCaptureField, ...]
    ui_language: str | None
