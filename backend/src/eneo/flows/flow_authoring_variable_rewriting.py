from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, cast

from eneo.flows.domain.flow_step_validation import FlowStepValidationView
from eneo.flows.enums import (
    FlowInputSource,
    FlowInputType,
    FlowOutputMode,
    FlowOutputType,
)
from eneo.flows.flow_authoring_spec import AssistantSpec, StepSpec
from eneo.flows.input_binding_contract_rules import (
    SOURCE_REFS_BINDING_KEY,
    source_ref_bindings,
)
from eneo.flows.variable_resolver import (
    TEMPLATE_VARIABLE_PATTERN,
    runtime_step_alias,
    runtime_step_alias_order,
)

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
        )

    if step_spec.input_bindings:
        rewritten_bindings = rewrite_variable_value(
            step_spec.input_bindings, ref_to_order
        )
        rewritten_bindings = rewrite_source_ref_step_refs(
            rewritten_bindings, ref_to_order
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
            input_config=step.input_config,
            output_config=step.output_config,
            review_policy=step.review_policy,
            prompt_template=step.assistant_spec.instructions,
        )
        for index, step in enumerate(rewritten_steps)
    ]


def renumber_step_aliases(value: Any, renumbering: Mapping[int, int]) -> Any:
    """`value` with the runtime alias (`step_N`) at the head of each template
    expression renumbered when its step changed position, and nothing else: the
    author's spacing and every other character stay. An expression and an
    alias are what the runtime resolver reads as one, so an unclosed
    expression, `step_02` or a numeral in another script is left as it is."""

    if not renumbering:
        return value
    if isinstance(value, str):
        return TEMPLATE_VARIABLE_PATTERN.sub(
            lambda match: _renumber_expression(match, renumbering), value
        )
    if isinstance(value, dict):
        return {
            key: renumber_step_aliases(inner, renumbering)
            for key, inner in cast(dict[str, Any], value).items()
        }
    if isinstance(value, list):
        return [
            renumber_step_aliases(item, renumbering) for item in cast(list[Any], value)
        ]
    return value


def _renumber_expression(match: re.Match[str], renumbering: Mapping[int, int]) -> str:
    whole = match.group(0)
    expression_start = match.start(1) - match.start(0)
    expression = match.group(1)
    head = expression.split(".", maxsplit=1)[0]
    name = head.strip()
    order = runtime_step_alias_order(name)
    if order is None or order not in renumbering or not expression.startswith(name):
        return whole
    return (
        whole[:expression_start]
        + runtime_step_alias(renumbering[order])
        + whole[expression_start + len(name) :]
    )


def renumber_input_binding_aliases(
    input_bindings: dict[str, Any] | None, renumbering: Mapping[int, int]
) -> dict[str, Any] | None:
    """`input_bindings` with the aliases in its templates and the `step_ref` of
    each source ref renumbered when their step changed position."""

    if input_bindings is None or not renumbering:
        return input_bindings
    renumbered = cast(
        dict[str, Any], renumber_step_aliases(input_bindings, renumbering)
    )
    source_refs = renumbered.get(SOURCE_REFS_BINDING_KEY)
    if isinstance(source_refs, list):
        renumbered[SOURCE_REFS_BINDING_KEY] = [
            _renumber_source_ref(item, renumbering)
            for item in cast(list[Any], source_refs)
        ]
    return renumbered


def _renumber_source_ref(source_ref: Any, renumbering: Mapping[int, int]) -> Any:
    if not isinstance(source_ref, dict):
        return source_ref
    payload = cast(dict[str, Any], source_ref)
    step_ref = payload.get("step_ref")
    order = runtime_step_alias_order(step_ref) if isinstance(step_ref, str) else None
    if order is None or order not in renumbering:
        return payload
    return {**payload, "step_ref": runtime_step_alias(renumbering[order])}


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


def rewrite_source_ref_step_refs(
    input_bindings: Any,
    ref_to_order: dict[str, int],
) -> Any:
    if not isinstance(input_bindings, dict):
        return input_bindings
    bindings = cast(dict[str, Any], input_bindings)
    if SOURCE_REFS_BINDING_KEY not in bindings:
        return bindings

    refs = source_ref_bindings(bindings)
    rewritten_refs: list[dict[str, object]] = []
    changed = False
    for ref in refs:
        payload = ref.binding_payload()
        runtime_order = ref_to_order.get(ref.step_ref)
        if runtime_order is not None:
            payload["step_ref"] = f"step_{runtime_order}"
            changed = True
        rewritten_refs.append(payload)

    if not changed:
        return bindings
    rewritten_bindings: dict[str, Any] = {
        **bindings,
        SOURCE_REFS_BINDING_KEY: rewritten_refs,
    }
    return rewritten_bindings
