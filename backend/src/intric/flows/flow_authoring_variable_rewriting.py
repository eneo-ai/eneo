from __future__ import annotations

import re
from typing import Any, cast

from intric.flows.domain.flow_step_validation import FlowStepValidationView
from intric.flows.enums import (
    FlowInputSource,
    FlowInputType,
    FlowMcpPolicy,
    FlowOutputMode,
    FlowOutputType,
)
from intric.flows.flow_authoring_spec import AssistantSpec, StepSpec

_TEMPLATE_EXPRESSION_PATTERN = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")


def build_ref_to_order(step_specs: list[StepSpec]) -> dict[str, int]:
    return {
        step_spec.plan_step_ref: index + 1 for index, step_spec in enumerate(step_specs)
    }


def rewrite_step_spec_variables(
    step_spec: StepSpec,
    ref_to_order: dict[str, int],
) -> StepSpec:
    """Rewrite draft plan_step_ref variables to runtime step_N variables."""
    updates: dict[str, Any] = {}

    rewritten_instructions = rewrite_variable_string(
        step_spec.assistant_spec.instructions,
        ref_to_order,
    )
    if rewritten_instructions != step_spec.assistant_spec.instructions:
        updates["assistant_spec"] = AssistantSpec(
            instructions=rewritten_instructions,
            model_ref=step_spec.assistant_spec.model_ref,
            knowledge_refs=list(step_spec.assistant_spec.knowledge_refs),
            mcp_server_refs=list(step_spec.assistant_spec.mcp_server_refs),
            mcp_tool_refs=list(step_spec.assistant_spec.mcp_tool_refs),
        )

    if step_spec.input_bindings:
        rewritten_bindings = rewrite_variable_value(
            step_spec.input_bindings, ref_to_order
        )
        if rewritten_bindings != step_spec.input_bindings:
            updates["input_bindings"] = rewritten_bindings

    if step_spec.output_config:
        rewritten_output_config = rewrite_variable_value(
            step_spec.output_config,
            ref_to_order,
        )
        if rewritten_output_config != step_spec.output_config:
            updates["output_config"] = rewritten_output_config

    if updates:
        return step_spec.model_copy(update=updates)
    return step_spec


def flow_step_validation_views_from_draft_spec(
    step_specs: list[StepSpec],
) -> list[FlowStepValidationView]:
    ref_to_order = build_ref_to_order(step_specs)
    rewritten_steps = [
        rewrite_step_spec_variables(step, ref_to_order) for step in step_specs
    ]
    return [
        FlowStepValidationView(
            step_order=index + 1,
            timeout_seconds=None,
            user_description=step.name,
            input_source=FlowInputSource(step.input_source.value),
            input_type=FlowInputType(step.input_type.value),
            input_contract=step.input_contract,
            output_mode=FlowOutputMode(step.output_mode.value),
            output_type=FlowOutputType(step.output_type.value),
            output_contract=step.output_contract,
            input_bindings=step.input_bindings,
            mcp_policy=FlowMcpPolicy(step.mcp_policy.value),
            input_config=step.input_config,
            output_config=step.output_config,
            review_policy=step.review_policy,
        )
        for index, step in enumerate(rewritten_steps)
    ]


def rewrite_variable_string(
    text: str,
    ref_to_order: dict[str, int],
) -> str:
    def replacer(match: re.Match[str]) -> str:
        expression = match.group(1).strip()
        if "." in expression:
            ref_name, tail = expression.split(".", maxsplit=1)
        else:
            ref_name, tail = expression, ""
        ref_name = ref_name.strip()
        if ref_name in ref_to_order:
            rewritten_head = f"step_{ref_to_order[ref_name]}"
            rewritten_expression = (
                f"{rewritten_head}.{tail.strip()}" if tail else rewritten_head
            )
            return "{{ " + rewritten_expression + " }}"
        return match.group(0)

    return _TEMPLATE_EXPRESSION_PATTERN.sub(replacer, text)


def rewrite_variable_value(
    value: Any,
    ref_to_order: dict[str, int],
) -> Any:
    if isinstance(value, str):
        return rewrite_variable_string(value, ref_to_order)
    if isinstance(value, dict):
        return {
            key: rewrite_variable_value(inner_value, ref_to_order)
            for key, inner_value in cast(dict[str, Any], value).items()
        }
    if isinstance(value, list):
        return [
            rewrite_variable_value(item, ref_to_order)
            for item in cast(list[Any], value)
        ]
    return value
