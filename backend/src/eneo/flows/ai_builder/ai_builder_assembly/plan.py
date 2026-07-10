from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from eneo.flows.ai_builder.ai_builder_new_step_models import (
    DocumentDeliveryMode,
    PreviousFieldRef,
    StructuredFieldDraft,
)
from eneo.flows.ai_builder.ai_builder_source_reader_contracts import (
    SourceCaptureField,
    source_capture_fields_from_terminal_schema,
    source_reader_leaf_field_name,
    structured_fields_have_document_items,
    structured_fields_have_source_leaf,
)
from eneo.flows.ai_builder.planning_state import AggregationIntent
from eneo.flows.domain.flow import RuntimeInputExecutionMode
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
from eneo.flows.input_binding_contract_rules import (
    field_refs_cover_whole_structured_object,
)
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
    "flow_input",
    "implicit_previous",
    "whole_object",
    "field_refs",
    "fan_in",
]
_LOCALIZED_SCHEMA_KEYS = frozenset({"sammanfattning"})


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
    runtime_input_execution_mode: RuntimeInputExecutionMode = "single_call"
    previous_item_map_enabled: bool = False
    form_field_refs: tuple[str, ...] = ()
    previous_field_refs: tuple[PreviousFieldRef, ...] = ()
    output_fields: tuple[StructuredFieldDraft, ...] = ()
    model_ref: str | None = None
    knowledge_refs: tuple[str, ...] = ()
    mcp_server_refs: tuple[str, ...] = ()
    mcp_tool_refs: tuple[str, ...] = ()
    citations_requested: bool = False
    review_mode: FlowStepReviewMode | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("Planned steps require a non-empty name.")
        if not self.instructions.strip():
            raise ValueError(
                f"Planned step {self.name!r} requires non-empty instructions."
            )
        if "{{" in self.instructions or "}}" in self.instructions:
            raise ValueError(
                f"Planned step {self.name!r} instructions must not contain "
                "template variables."
            )
        _validate_underlag_channel_shape(self)
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
            planned_step_is_source_reader(step) for step in self.steps
        ):
            raise ValueError(
                "FlowAssemblyPlan source_reader_required_fields require a "
                "source-reader planned step."
            )
        _validate_output_field_schema_keys(self.steps)
        _validate_source_reader_contracts_complete(
            steps=self.steps,
            terminal_output_schema=self.terminal_output_schema,
            required_fields=self.source_reader_required_fields,
        )
        _validate_per_source_reader_contracts(self.steps)


def _validate_underlag_channel_shape(step: PlannedStep) -> None:
    if step.input_source == InputSource.FLOW_INPUT:
        if step.underlag_channel != "flow_input":
            raise ValueError(
                f"Planned step {step.name!r} declares underlag_channel "
                f"{step.underlag_channel!r}; expected 'flow_input'."
            )
        if step.previous_field_refs:
            raise ValueError(
                f"Planned step {step.name!r} cannot reference previous output "
                "while reading flow input."
            )
        return
    if step.input_source == InputSource.ALL_PREVIOUS_STEPS:
        if step.underlag_channel != "fan_in":
            raise ValueError(
                f"Planned step {step.name!r} declares underlag_channel "
                f"{step.underlag_channel!r}; expected 'fan_in'."
            )
        if step.form_field_refs or step.previous_field_refs:
            raise ValueError(
                f"Planned step {step.name!r} cannot combine fan-in with "
                "explicit form fields or previous refs."
            )
        return
    if step.previous_field_refs:
        if step.underlag_channel not in {"field_refs", "whole_object"}:
            raise ValueError(
                f"Planned step {step.name!r} declares underlag_channel "
                f"{step.underlag_channel!r}; expected field refs or whole object."
            )
        return
    if step.underlag_channel not in {"implicit_previous", "whole_object"}:
        raise ValueError(
            f"Planned step {step.name!r} declares underlag_channel "
            f"{step.underlag_channel!r}; expected implicit previous or whole object."
        )


def derive_underlag_channel(
    *,
    input_source: InputSource,
    input_type: InputType,
    previous_step: PlannedStep | None,
    previous_field_refs: tuple[PreviousFieldRef, ...],
) -> UnderlagChannel:
    if input_source == InputSource.FLOW_INPUT:
        return "flow_input"
    if input_source == InputSource.ALL_PREVIOUS_STEPS:
        return "fan_in"
    if previous_field_refs:
        if (
            previous_step is not None
            and previous_step.output_type == OutputType.JSON
            and field_refs_cover_whole_structured_object(
                field_paths=(ref.field_path for ref in previous_field_refs),
                property_names=(field.name for field in previous_step.output_fields),
            )
        ):
            return "whole_object"
        return "field_refs"
    if (
        previous_step is not None
        and previous_step.output_type == OutputType.JSON
        and input_type == InputType.TEXT
    ):
        return "whole_object"
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
        previous_step = steps[index - 1]
        expected_underlag_channel = derive_underlag_channel(
            input_source=step.input_source,
            input_type=step.input_type,
            previous_step=(
                previous_step
                if step.input_source == InputSource.PREVIOUS_STEP
                else None
            ),
            previous_field_refs=step.previous_field_refs,
        )
        if step.underlag_channel != expected_underlag_channel:
            raise ValueError(
                f"Planned step {step.name!r} declares underlag_channel "
                f"{step.underlag_channel!r}; expected "
                f"{expected_underlag_channel!r}."
            )
        if step.input_source != InputSource.PREVIOUS_STEP:
            continue
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
    for ref in step.previous_field_refs:
        if ref.from_step < 1 or ref.from_step > expected_from_step:
            raise ValueError(
                f"Planned step {step.name!r} references step {ref.from_step}; "
                f"expected an earlier step no later than {expected_from_step}."
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


def planned_step_is_source_reader(step: PlannedStep) -> bool:
    return (
        step.input_source == InputSource.FLOW_INPUT
        and step.input_type in {InputType.DOCUMENT, InputType.FILE, InputType.TEXT}
        and step.output_type == OutputType.JSON
        and bool(step.output_fields)
    )


def _validate_source_reader_contracts_complete(
    *,
    steps: tuple[PlannedStep, ...],
    terminal_output_schema: JsonObject | None,
    required_fields: tuple[SourceCaptureField, ...],
) -> None:
    source_reader_indexes = tuple(
        index for index, step in enumerate(steps) if planned_step_is_source_reader(step)
    )
    if not source_reader_indexes:
        return
    terminal_fields = (
        source_capture_fields_from_terminal_schema(terminal_output_schema)
        if terminal_output_schema is not None
        else ()
    )
    missing_names: set[str] = set()
    for field in (*required_fields, *terminal_fields):
        if not any(
            structured_fields_have_source_leaf(
                steps[index].output_fields,
                field.name,
            )
            for index in source_reader_indexes
        ):
            missing_names.add(field.name)
    for step in steps:
        for ref in step.previous_field_refs:
            source_index = ref.from_step - 1
            if source_index not in source_reader_indexes:
                continue
            field_name = source_reader_leaf_field_name(ref.field_path)
            if field_name and not structured_fields_have_source_leaf(
                steps[source_index].output_fields,
                field_name,
            ):
                missing_names.add(field_name)
    if missing_names:
        raise ValueError(
            "FlowAssemblyPlan source-reader output fields must be complete "
            f"before lowering: {', '.join(sorted(missing_names))}."
        )


def _validate_output_field_schema_keys(steps: tuple[PlannedStep, ...]) -> None:
    invalid_paths = [
        f"{step.name}.{field_path}"
        for step in steps
        for field_path, field_name in _structured_field_paths(step.output_fields)
        if not _is_ascii_english_schema_key(field_name)
    ]
    if invalid_paths:
        raise ValueError(
            "FlowAssemblyPlan output field keys must be ASCII English schema "
            "keys; put localized labels in descriptions instead: "
            f"{', '.join(invalid_paths)}."
        )


def _structured_field_paths(
    fields: tuple[StructuredFieldDraft, ...] | list[StructuredFieldDraft],
    *,
    parent_path: str | None = None,
) -> tuple[tuple[str, str], ...]:
    paths: list[tuple[str, str]] = []
    for field in fields:
        field_path = (
            f"{parent_path}.{field.name}" if parent_path is not None else field.name
        )
        paths.append((field_path, field.name))
        nested_fields = (
            field.fields if field.field_type == "object" else field.item_fields
        )
        if nested_fields:
            paths.extend(_structured_field_paths(nested_fields, parent_path=field_path))
    return tuple(paths)


def _is_ascii_english_schema_key(field_name: str) -> bool:
    return field_name.isascii() and field_name.casefold() not in _LOCALIZED_SCHEMA_KEYS


def _validate_per_source_reader_contracts(steps: tuple[PlannedStep, ...]) -> None:
    for step in steps:
        if step.runtime_input_execution_mode != "per_source":
            continue
        if len(step.output_fields) == 1 and structured_fields_have_document_items(
            step.output_fields
        ):
            continue
        raise ValueError(
            "Per-source source-reader steps must output exactly one documents[] "
            f"field; {step.name!r} declares a corpus-level reader contract."
        )
