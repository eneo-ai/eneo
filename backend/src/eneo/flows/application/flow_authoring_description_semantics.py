"""Semantic signature used when rewriting Flow descriptions."""

from __future__ import annotations

from pydantic import BaseModel

from eneo.flows.domain.flow import FlowStep
from eneo.flows.flow_authoring_spec import (
    InputSource,
    InputType,
    OutputMode,
    OutputType,
    StepSpec,
)


class FlowSemanticSignature(BaseModel):
    """Captures the semantic identity of a flow: what goes in and what comes out."""

    entry_input_type: str | None = None
    entry_input_source: str | None = None
    terminal_output_type: str | None = None
    terminal_output_mode: str | None = None

    @classmethod
    def from_steps(cls, steps: list[StepSpec]) -> FlowSemanticSignature:
        if not steps:
            return cls()
        entry = steps[0]
        terminal = steps[-1]
        return cls(
            entry_input_type=entry.input_type.value,
            entry_input_source=entry.input_source.value,
            terminal_output_type=terminal.output_type.value,
            terminal_output_mode=terminal.output_mode.value,
        )

    @classmethod
    def from_flow_steps(cls, steps: list[FlowStep]) -> FlowSemanticSignature:
        entry_input_source: str | None = None
        entry_input_type: str | None = None
        terminal_output_mode: str | None = None
        terminal_output_type: str | None = None

        # Coerce every step so unsupported persisted vocabulary anywhere is loud.
        for step in steps:
            input_source = InputSource(step.input_source).value
            input_type = InputType(step.input_type).value
            terminal_output_mode = OutputMode(step.output_mode).value
            terminal_output_type = OutputType(step.output_type).value
            if entry_input_source is None:
                entry_input_source = input_source
                entry_input_type = input_type

        return cls(
            entry_input_source=entry_input_source,
            entry_input_type=entry_input_type,
            terminal_output_mode=terminal_output_mode,
            terminal_output_type=terminal_output_type,
        )

    def has_semantic_change(self, other: FlowSemanticSignature) -> bool:
        return self != other
