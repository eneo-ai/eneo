"""Semantic signature used when rewriting Flow descriptions."""

from __future__ import annotations

from pydantic import BaseModel

from intric.flows.flow_authoring_spec import StepSpec


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

    def has_semantic_change(self, other: FlowSemanticSignature) -> bool:
        return self != other
