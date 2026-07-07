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
from eneo.flows.ai_builder.planning_state import AggregationIntent
from eneo.flows.enums import (
    FlowInputSource,
    FlowInputType,
    FlowOutputMode,
    FlowOutputType,
)
from eneo.flows.flow_authoring_spec import (
    FormFieldSpec,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
)
from eneo.flows.flow_capability_manifest import (
    is_chain_compatible,
    resolve_capability_for_tuple,
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

    def __post_init__(self) -> None:
        if self.previous_field_refs and self.previous_output_refs:
            raise ValueError(
                f"Planned step {self.name!r} cannot mix previous field refs "
                "and previous output refs."
            )
        expected_underlag_channel = _expected_underlag_channel(self)
        if self.underlag_channel != expected_underlag_channel:
            raise ValueError(
                f"Planned step {self.name!r} declares underlag_channel "
                f"{self.underlag_channel!r}; expected "
                f"{expected_underlag_channel!r}."
            )
        if self.runtime_max_files is not None and self.runtime_max_files < 1:
            raise ValueError(
                f"Planned step {self.name!r} has runtime_max_files below 1."
            )
        if not _step_capabilities_are_supported(self):
            raise ValueError(
                f"Planned step {self.name!r} uses an unsupported capability "
                "tuple: "
                f"input_source={self.input_source.value!r}, "
                f"input_type={self.input_type.value!r}, "
                f"output_type={self.output_type.value!r}, "
                f"output_mode={self.output_mode.value!r}."
            )


@dataclass(frozen=True, slots=True)
class FlowAssemblyPlan:
    flow_name: str
    flow_description: str
    form_fields: tuple[FormFieldSpec, ...]
    steps: tuple[PlannedStep, ...]
    terminal_output_schema: JsonObject | None
    source_reader_required_fields: tuple[SourceCaptureField, ...]
    aggregation_intent: AggregationIntent
    ui_language: str | None

    def __post_init__(self) -> None:
        if not self.steps:
            raise ValueError("FlowAssemblyPlan requires at least one planned step.")
        _validate_step_order(
            self.steps,
            aggregation_intent=self.aggregation_intent,
        )
        _validate_form_field_placement(
            form_fields=self.form_fields,
            steps=self.steps,
        )
        if self.terminal_output_schema is not None:
            terminal_step = self.steps[-1]
            if terminal_step.output_type != OutputType.JSON:
                raise ValueError(
                    "FlowAssemblyPlan terminal_output_schema requires a JSON "
                    "terminal step."
                )
        if self.source_reader_required_fields and not any(
            _planned_step_is_source_reader(step) for step in self.steps
        ):
            raise ValueError(
                "FlowAssemblyPlan source_reader_required_fields require a "
                "source-reader planned step."
            )


def _expected_underlag_channel(step: PlannedStep) -> UnderlagChannel:
    if step.input_source == InputSource.FLOW_INPUT:
        if step.previous_field_refs or step.previous_output_refs:
            raise ValueError(
                f"Planned step {step.name!r} cannot reference previous output "
                "while reading flow input."
            )
        return "flow_input"
    if step.input_source == InputSource.ALL_PREVIOUS_STEPS:
        if (
            step.form_field_refs
            or step.previous_field_refs
            or step.previous_output_refs
        ):
            raise ValueError(
                f"Planned step {step.name!r} cannot combine fan-in with "
                "explicit form fields or previous refs."
            )
        return "fan_in"
    if step.previous_field_refs:
        return "field_refs"
    if step.previous_output_refs:
        return "text_anchor"
    return "implicit_previous"


def _step_capabilities_are_supported(step: PlannedStep) -> bool:
    return (
        resolve_capability_for_tuple(
            input_source=FlowInputSource(step.input_source.value),
            input_type=FlowInputType(step.input_type.value),
            output_type=FlowOutputType(step.output_type.value),
            output_mode=FlowOutputMode(step.output_mode.value),
        )
        is not None
    )


def _validate_step_order(
    steps: tuple[PlannedStep, ...],
    *,
    aggregation_intent: AggregationIntent,
) -> None:
    for index, step in enumerate(steps):
        if index == 0:
            if step.input_source != InputSource.FLOW_INPUT:
                raise ValueError(
                    "The first FlowAssemblyPlan step must read flow input."
                )
            continue
        if step.input_source == InputSource.FLOW_INPUT:
            raise ValueError(
                "Only the first FlowAssemblyPlan step may read flow input."
            )
        if (
            step.input_source == InputSource.ALL_PREVIOUS_STEPS
            and aggregation_intent == "linear"
        ):
            raise ValueError(
                "FlowAssemblyPlan fan-in requires aggregate or compare intent."
            )
        _validate_previous_refs(step, expected_from_step=index)
        if step.input_source != InputSource.PREVIOUS_STEP:
            continue
        previous_step = steps[index - 1]
        if not is_chain_compatible(
            output_type=FlowOutputType(previous_step.output_type.value),
            input_type=FlowInputType(step.input_type.value),
        ):
            raise ValueError(
                f"Planned step {step.name!r} cannot read previous step "
                f"{previous_step.name!r}: "
                f"{previous_step.output_type.value!r} -> "
                f"{step.input_type.value!r} is not chain-compatible."
            )


def _validate_previous_refs(step: PlannedStep, *, expected_from_step: int) -> None:
    for ref in (*step.previous_field_refs, *step.previous_output_refs):
        if ref.from_step != expected_from_step:
            raise ValueError(
                f"Planned step {step.name!r} references step {ref.from_step}; "
                f"expected immediate previous step {expected_from_step}."
            )


def _validate_form_field_placement(
    *,
    form_fields: tuple[FormFieldSpec, ...],
    steps: tuple[PlannedStep, ...],
) -> None:
    declared_names = {field.name for field in form_fields}
    placed_names = {field_name for step in steps for field_name in step.form_field_refs}
    unknown_names = placed_names - declared_names
    if unknown_names:
        raise ValueError(
            "FlowAssemblyPlan references undeclared form fields: "
            f"{', '.join(sorted(unknown_names))}."
        )
    unplaced_names = declared_names - placed_names
    if unplaced_names:
        raise ValueError(
            "FlowAssemblyPlan declares form fields with no step placement: "
            f"{', '.join(sorted(unplaced_names))}."
        )


def _planned_step_is_source_reader(step: PlannedStep) -> bool:
    return (
        step.input_source == InputSource.FLOW_INPUT
        and step.input_type in {InputType.DOCUMENT, InputType.FILE, InputType.TEXT}
        and step.output_type == OutputType.JSON
        and bool(step.output_fields)
    )
