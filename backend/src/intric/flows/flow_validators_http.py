from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from intric.flows.domain.flow import FlowPersistedJsonObject
from intric.flows.domain.flow_step_validation import (
    FlowStepValidationError,
    FlowStepValidationView,
)
from intric.flows.http_transport import (
    HttpAuthoredConfig,
    is_authored_config,
    validate_authored_config,
)
from intric.main.config import get_settings


def validate_http_input_config(*, step: FlowStepValidationView) -> None:
    if step.input_type in {"document", "file", "image", "audio"}:
        raise FlowStepValidationError(
            f"Step {step.step_order}: input_type '{step.input_type}' is not supported with input_source '{step.input_source}'.",
            step_order=step.step_order,
        )
    method = "GET" if step.input_source == "http_get" else "POST"
    validate_http_config(
        step_order=step.step_order,
        label="input_config",
        config=step.input_config,
        method=method,
        direction="input",
    )


def validate_http_output_config(*, step: FlowStepValidationView) -> None:
    validate_http_config(
        step_order=step.step_order,
        label="output_config",
        config=step.output_config,
        method="POST",
        direction="output",
    )


def validate_http_config(
    *,
    step_order: int,
    label: str,
    config: FlowPersistedJsonObject | None,
    method: str,
    direction: str,
) -> None:
    authored_config = _require_authored_http_config(
        step_order=step_order,
        label=label,
        config=config,
    )
    validate_authored_http_config(
        step_order=step_order,
        label=label,
        config=authored_config,
        method=method,
        direction=direction,
    )


def validate_authored_http_config(
    *,
    step_order: int,
    label: str,
    config: dict[str, Any],
    method: str,
    direction: str,
) -> None:
    max_timeout = float(get_settings().flow_http_max_timeout_seconds)
    try:
        authored = HttpAuthoredConfig.model_validate(config)
    except ValidationError as exc:
        raise FlowStepValidationError(
            f"Step {step_order}: {label} is not a valid HTTP config: {exc}",
            step_order=step_order,
        ) from exc
    errors = validate_authored_config(
        authored, direction=direction, method=method, max_timeout=max_timeout
    )
    if errors:
        raise FlowStepValidationError(
            f"Step {step_order}: {label} validation failed: {errors[0].value}",
            step_order=step_order,
        )


def _require_authored_http_config(
    *,
    step_order: int,
    label: str,
    config: FlowPersistedJsonObject | None,
) -> dict[str, Any]:
    if not isinstance(config, dict) or not is_authored_config(config):
        raise FlowStepValidationError(
            f"Step {step_order}: {label} must use authored HTTP config with an auth field; "
            "legacy flat HTTP config is no longer supported.",
            step_order=step_order,
        )
    return config
