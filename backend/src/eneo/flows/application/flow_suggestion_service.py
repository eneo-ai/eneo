"""Suggestions for a draft flow, computed from the saved draft and the prompts
of its step assistants; writes nothing."""

from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

from eneo.flows.domain.flow import Flow, FlowStep
from eneo.flows.domain.flow_suggestions import (
    FlowSuggestion,
    SuggestionStep,
    analyze_flow,
)
from eneo.flows.enums import flow_output_mode_uses_completion_model
from eneo.main.container.container import Container


def suggestion_step(step: FlowStep, *, prompt_text: str | None) -> SuggestionStep:
    """The analyzer's view of a saved step. The prompt counts as a read only
    when a completion model reads it, as the classification rule counts it."""
    assert step.id is not None, "a saved step has an id"
    return SuggestionStep(
        id=step.id,
        step_order=step.step_order,
        user_description=step.user_description,
        input_source=step.input_source,
        input_type=step.input_type,
        input_bindings=step.input_bindings,
        input_config=step.input_config,
        output_mode=step.output_mode,
        output_type=step.output_type,
        output_contract=step.output_contract,
        output_config=step.output_config,
        prompt_text=(
            prompt_text
            if flow_output_mode_uses_completion_model(step.output_mode)
            else None
        ),
        assistant_id=step.assistant_id,
    )


def flow_suggestions(
    flow: Flow, *, prompts: Mapping[UUID, str]
) -> tuple[FlowSuggestion, ...]:
    """Every suggestion the draft proves, given the saved prompt of each step
    assistant (an assistant without one reads as an empty prompt)."""
    return analyze_flow(
        [
            suggestion_step(step, prompt_text=prompts.get(step.assistant_id))
            for step in flow.steps
            if step.id is not None
        ]
    )


async def list_flow_suggestions(
    *, container: Container, flow: Flow
) -> tuple[FlowSuggestion, ...]:
    """The suggestions of ``flow``'s draft. The prompts are read once for all
    of its assistants, tenant-scoped, as the step-kinds answer reads them.
    The caller has decided that the user may edit the flow."""
    stored = await container.flow_service().get_flow_assistant_prompts(flow)
    return flow_suggestions(
        flow,
        prompts={assistant_id: prompt.text for assistant_id, prompt in stored.items()},
    )


__all__ = ["flow_suggestions", "list_flow_suggestions", "suggestion_step"]
