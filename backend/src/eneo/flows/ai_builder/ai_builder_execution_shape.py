"""Factual static execution shape derived from a compiled Builder proposal."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from eneo.flows.domain.runtime_input import build_runtime_input_config
from eneo.flows.domain.step_mapped_execution import (
    FlowStepMappedExecutionConfigurationError,
    resolve_step_mapped_execution,
)
from eneo.flows.enums import (
    FlowOutputMode,
    FlowPrimaryOutputExecutionKind,
    flow_output_mode_primary_execution_kind,
)
from eneo.flows.flow_authoring_spec import FlowDraftSpecCore, InputType, StepSpec


class FlowBuilderMappedStepUpperBound(BaseModel):
    """Authored logical-item ceiling for one mapped step."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    plan_step_ref: str = Field(min_length=1)
    execution_mode: Literal["per_source", "per_item"]
    maximum_items: int = Field(ge=1)


class FlowBuilderExecutionShape(BaseModel):
    """Static proposal facts; counts are not provider-call estimates."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    completion_model_step_count: int = Field(ge=0)
    transcription_model_step_count: int = Field(ge=0)
    deterministic_step_count: int = Field(ge=0)
    schema_constrained_step_count: int = Field(ge=0)
    mapped_step_upper_bounds: tuple[FlowBuilderMappedStepUpperBound, ...] = ()


def build_flow_builder_execution_shape(
    spec: FlowDraftSpecCore,
) -> FlowBuilderExecutionShape:
    completion_model_steps = 0
    transcription_model_steps = 0
    deterministic_steps = 0
    schema_constrained_steps = 0
    mapped_bounds: list[FlowBuilderMappedStepUpperBound] = []

    for step in spec.steps:
        output_execution_kind = flow_output_mode_primary_execution_kind(
            FlowOutputMode(step.output_mode.value)
        )
        uses_completion_model = (
            output_execution_kind is FlowPrimaryOutputExecutionKind.COMPLETION_MODEL
        )
        uses_transcription_model = _step_uses_transcription_model(
            step=step,
            output_execution_kind=output_execution_kind,
        )

        completion_model_steps += int(uses_completion_model)
        transcription_model_steps += int(uses_transcription_model)
        deterministic_steps += int(
            not uses_completion_model and not uses_transcription_model
        )
        schema_constrained_steps += int(step.output_contract is not None)

        mapped_bound = _authored_mapped_upper_bound(step)
        if mapped_bound is not None:
            mapped_bounds.append(mapped_bound)

    return FlowBuilderExecutionShape(
        completion_model_step_count=completion_model_steps,
        transcription_model_step_count=transcription_model_steps,
        deterministic_step_count=deterministic_steps,
        schema_constrained_step_count=schema_constrained_steps,
        mapped_step_upper_bounds=tuple(mapped_bounds),
    )


def _step_uses_transcription_model(
    *,
    step: StepSpec,
    output_execution_kind: FlowPrimaryOutputExecutionKind,
) -> bool:
    if output_execution_kind is FlowPrimaryOutputExecutionKind.TRANSCRIPTION_MODEL:
        return True
    if step.input_type is InputType.AUDIO:
        return True
    runtime_input = build_runtime_input_config(step.input_config)
    return runtime_input.enabled and runtime_input.input_format == "audio"


def _authored_mapped_upper_bound(
    step: StepSpec,
) -> FlowBuilderMappedStepUpperBound | None:
    try:
        mapped_execution = resolve_step_mapped_execution(
            input_source=step.input_source,
            input_type=step.input_type,
            output_mode=step.output_mode,
            output_type=step.output_type,
            input_config=step.input_config,
        )
    except FlowStepMappedExecutionConfigurationError:
        return None
    if mapped_execution is None or mapped_execution.maximum_items is None:
        return None
    return FlowBuilderMappedStepUpperBound(
        plan_step_ref=step.plan_step_ref,
        execution_mode=mapped_execution.execution_mode,
        maximum_items=mapped_execution.maximum_items,
    )


__all__ = [
    "FlowBuilderExecutionShape",
    "FlowBuilderMappedStepUpperBound",
    "build_flow_builder_execution_shape",
]
