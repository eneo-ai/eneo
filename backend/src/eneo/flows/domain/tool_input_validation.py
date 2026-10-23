from __future__ import annotations

from pydantic import ValidationError

from eneo.flows.domain.flow_step_validation import (
    FlowStepValidationError,
    FlowStepValidationView,
)
from eneo.flows.domain.tool_input import (
    TOOL_INPUT_CONFIG_KEY,
    TOOL_INPUT_TYPES,
    ToolArgumentError,
    ToolInputConfig,
    read_tool_input_config,
)
from eneo.flows.enums import FlowInputType
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.output_modes import outside_input_mode_violation

_FIELD = f"input_config.{TOOL_INPUT_CONFIG_KEY}"


def validate_tool_input_config(*, step: FlowStepValidationView) -> ToolInputConfig:
    """The tool configuration of a tool step, or the refusal of a step whose
    input type, output mode, configuration or arguments cannot be used. Which
    values the bound arguments name is not judged here."""
    if step.input_type not in TOOL_INPUT_TYPES:
        raise invalid_tool_config(
            f"Step {step.step_order}: input_type "
            f"'{FlowInputType(step.input_type).value}' is not supported with "
            "input_source 'tool'.",
            step_order=step.step_order,
            context={"field": "input_type"},
        )
    mode_violation = outside_input_mode_violation(
        input_source=step.input_source, output_mode=step.output_mode
    )
    if mode_violation is not None:
        raise invalid_tool_config(
            f"Step {step.step_order}: {mode_violation}.",
            step_order=step.step_order,
            context={"field": "output_mode"},
        )
    try:
        config = read_tool_input_config(step.input_config)
    except ValidationError as exc:
        # Pydantic's message quotes the input value; only the location goes on.
        field = ".".join((_FIELD, *(str(part) for part in exc.errors()[0]["loc"])))
        raise invalid_tool_config(
            f"Step {step.step_order}: {field} is not a valid tool configuration value.",
            step_order=step.step_order,
            context={"field": field},
        ) from None
    try:
        config.bound_arguments()
    except ToolArgumentError as exc:
        raise invalid_tool_config(
            f"Step {step.step_order}: tool argument '{exc.argument}' must be a fixed "
            f"value or one whole reference ({exc.problem.value}).",
            step_order=step.step_order,
            context=tool_argument_context(exc.argument, exc.problem.value),
        ) from None
    return config


def tool_argument_context(argument: str, problem: str) -> dict[str, object]:
    return {
        "field": f"{_FIELD}.arguments.{argument}",
        "argument": argument,
        "problem": problem,
    }


def invalid_tool_config(
    message: str, *, step_order: int, context: dict[str, object]
) -> FlowStepValidationError:
    return FlowStepValidationError(
        message,
        step_order=step_order,
        code=FlowApiErrorCode.TYPED_IO_TOOL_INVALID_CONFIG,
        context=context,
    )
